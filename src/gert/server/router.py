"""API router for GERT server."""

import asyncio
import logging
import traceback
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    status,
)
from fastapi import Path as FastApiPath
from pydantic import BaseModel, Field

from gert.experiment_runner.experiment_orchestrator import ExperimentOrchestrator
from gert.experiments.models import (
    ExecutionState,
    ExperimentConfig,
    IngestionPayload,
)
from gert.storage.api import StorageAPI
from gert.storage.ingestion import IngestionReceiver

logger = logging.getLogger(__name__)

router = APIRouter(tags=["experiments"])


class StepStatus(BaseModel):
    """Status of an individual forward model step."""

    name: str
    status: str
    start_time: datetime | None = None
    end_time: datetime | None = None


class RealizationStatus(BaseModel):
    """Status of a specific realization execution including its steps."""

    realization_id: int
    iteration: int
    status: str
    steps: list[StepStatus] = Field(default_factory=list)


class StepLogResponse(BaseModel):
    """Response model for step execution logs."""

    stdout: str
    stderr: str


class ExperimentMetadata(BaseModel):
    """Bounds and metadata for an experiment."""

    experiment_id: str
    name: str
    num_iterations: int
    num_realizations: int
    num_fm_steps: int
    step_names: list[str]


class ExperimentResponse(BaseModel):
    """Response model for a newly created experiment."""

    id: str = Field(..., description="The unique experiment ID.")


class CompletePayload(BaseModel):
    """Payload for signaling realization completion."""

    source_step: str | None = None


class FailurePayload(BaseModel):
    """Payload for signaling realization failure."""

    source_step: str | None = None
    error: str
    traceback: str | None = None


# In-memory storage for experiment configurations (Mocked storage)
# In PR 2.1, this should move to a more persistent storage backend.
_experiment_configs: dict[str, ExperimentConfig] = {}
_executions_to_configs: dict[str, ExperimentConfig] = {}
_experiment_statuses: dict[
    str,
    dict[int, dict[int, RealizationStatus]],
] = defaultdict(lambda: defaultdict(dict))
_execution_states: dict[str, ExecutionState] = {}
_active_orchestrators: dict[str, "ExperimentOrchestrator"] = {}
_consolidation_tasks: set[asyncio.Task[Any]] = set()
_experiment_run_counts: dict[str, int] = defaultdict(int)
_latest_execution_id: dict[str, str] = {}


def _recover_execution(
    experiment_id: str,
    execution_id: str,
) -> tuple[ExperimentConfig | None, ExecutionState | None]:
    """Recover execution state from persistent storage if it's missing from memory."""
    if execution_id in _executions_to_configs and execution_id in _execution_states:
        return _executions_to_configs[execution_id], _execution_states[execution_id]

    base = Path("./permanent_storage")
    if not base.exists():
        return None, None

    for state_file in base.glob(f"*/{execution_id}/execution_state.json"):
        try:
            state = ExecutionState.model_validate_json(
                state_file.read_text(),
            )
            if state.experiment_id == experiment_id:
                # Load config from experiment level
                config_file = state_file.parent.parent / "config.json"
                if not config_file.exists():
                    logger.error(f"Config file missing for experiment {experiment_id}")
                    continue

                config = ExperimentConfig.model_validate_json(config_file.read_text())

                _experiment_configs[experiment_id] = config
                _executions_to_configs[execution_id] = config
                _execution_states[execution_id] = state
                return config, state
        except Exception:
            logger.exception("Failed to load execution state")
            continue

    return None, None


@router.post(
    "/experiments",
    status_code=status.HTTP_201_CREATED,
    summary="Create a new experiment",
    description="Registers an immutable experiment configuration and returns an ID.",
)
async def create_experiment(config: ExperimentConfig) -> ExperimentResponse:
    """Create a new experiment configuration."""
    experiment_id = uuid.uuid4().hex
    _experiment_configs[experiment_id] = config

    # Save config to storage

    api = StorageAPI(base_storage_path=config.storage_base)
    api.write_experiment_config(config)

    return ExperimentResponse(id=experiment_id)


@router.post(
    "/experiments/{experiment_id}/executions/{execution_id}/pause",
    summary="Pause an active execution",
    description="Halts the orchestrator macro loop. "
    "Graceful (waits until forward models finish) "
    "by default, forceful if force=true.",
)
async def pause_execution(
    experiment_id: str,
    execution_id: str,
    *,
    force: bool = False,
) -> dict[str, str]:
    """Pause an active execution.

    Raises:
        HTTPException: if execution was not found.
    """
    config, state = _recover_execution(experiment_id, execution_id)
    if not config or not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' not found",
        )

    if orchestrator := _active_orchestrators.get(execution_id):
        orchestrator.pause(force=force)
    # If the orchestrator is not actively running in memory, it might already be dead
    # We can update the state to PAUSED if it wasn't already.
    elif state.status not in {"PAUSED", "COMPLETED", "FAILED"}:
        state.status = "PAUSED"

        api = StorageAPI(base_storage_path=config.storage_base)
        api.write_execution_state(config.name, execution_id, state)

    return {"status": "success"}


@router.post(
    "/experiments/{experiment_id}/executions/{execution_id}/resume",
    summary="Resume a paused or crashed execution",
    description="Reads the state from permanent storage and resumes the orchestrator.",
)
async def resume_execution(
    experiment_id: str,
    execution_id: str,
) -> dict[str, str]:
    """Resume a paused or crashed execution.

    Raises:
        HTTPException: if the resume request is invalid.
    """
    config, state = _recover_execution(experiment_id, execution_id)
    if not config or not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' not found",
        )

    if execution_id in _active_orchestrators:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Execution '{execution_id}' is already running",
        )

    if state.status in {"COMPLETED", "FAILED"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot resume execution '{execution_id}' in state {state.status}",
        )

    def _monitoring_cb(
        realization_id: int,
        iteration: int,
        current_status: str,
        step_name: str | None,
    ) -> None:
        _update_realization_status(
            execution_id=execution_id,
            iteration=iteration,
            realization_id=realization_id,
            new_status=current_status,
            step_name=step_name,
        )

    api_url = "http://localhost:8000"

    orchestrator = ExperimentOrchestrator(
        config=config,
        experiment_id=experiment_id,
        run_count=1,  # Recovered execution keeps its ID from state
        monitoring_callback=_monitoring_cb,
        api_url=api_url,
        resume_state=state,
    )

    _active_orchestrators[execution_id] = orchestrator
    _execution_states[execution_id] = ExecutionState(
        experiment_id=experiment_id,
        execution_id=execution_id,
        status="RUNNING",
    )

    async def _run_wrapped() -> None:
        try:
            await orchestrator.run_experiment()
            if orchestrator.is_paused:
                _execution_states[execution_id].status = (
                    "PAUSED" if orchestrator.is_force_paused else "PAUSING"
                )
            else:
                _execution_states[execution_id].status = "COMPLETED"
        except Exception:
            error_msg = traceback.format_exc()
            _execution_states[execution_id].status = "FAILED"
            _execution_states[execution_id].error = error_msg
            logger.exception("Background execution failed")
        finally:
            _active_orchestrators.pop(execution_id, None)

            # Flush execution state to disk so it stays updated
            if execution_id in _execution_states:
                api = StorageAPI(base_storage_path=config.storage_base)
                api.write_execution_state(
                    config.name,
                    execution_id,
                    _execution_states[execution_id],
                )

    task = asyncio.create_task(_run_wrapped())
    _consolidation_tasks.add(task)
    task.add_done_callback(_consolidation_tasks.discard)

    return {"status": "success"}


@router.get(
    "/experiments/{experiment_id}/config",
    summary="Retrieve experiment configuration",
    description="Returns the immutable configuration for a given experiment ID.",
)
async def get_experiment_config(
    experiment_id: Annotated[
        str,
        FastApiPath(
            description="The unique experiment ID to retrieve.",
        ),
    ],
) -> ExperimentConfig:
    """Retrieve an experiment configuration by ID.

    Raises:
        HTTPException: If the experiment is not found.
    """
    if experiment_id not in _experiment_configs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Experiment '{experiment_id}' not found",
        )
    return _experiment_configs[experiment_id]


@router.get(
    "/experiments/{experiment_id}/metadata",
    summary="Retrieve experiment metadata",
    description="Returns bounds and metadata (num steps, realizations, etc) "
    "for an experiment.",
)
async def get_experiment_metadata(
    experiment_id: str,
) -> ExperimentMetadata:
    """Retrieve experiment metadata by ID.

    Raises:
        HTTPException: If the experiment is not found.
    """
    if experiment_id not in _experiment_configs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Experiment '{experiment_id}' not found",
        )
    config = _experiment_configs[experiment_id]

    num_realizations = len(
        config.parameter_matrix.get_realizations(config.base_working_directory),
    )
    num_fm_steps = len(config.forward_model_steps)
    step_names = [s.name for s in config.forward_model_steps]
    num_iterations = len(config.updates) + 1  # Prior + N updates

    return ExperimentMetadata(
        experiment_id=experiment_id,
        name=config.name,
        num_iterations=num_iterations,
        num_realizations=num_realizations,
        num_fm_steps=num_fm_steps,
        step_names=step_names,
    )


@router.post(
    "/experiments/{experiment_id}/start",
    summary="Start experiment",
    description="Launches the orchestration loop for a previously "
    "registered experiment.",
)
async def start_experiment(
    experiment_id: str,
) -> dict[str, Any]:
    """Start an experiment by ID.

    Raises:
        HTTPException: If the experiment is not found.
    """
    if experiment_id not in _experiment_configs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Experiment '{experiment_id}' not found",
        )

    config = _experiment_configs[experiment_id]

    # Validate environment-specific constraints (executables exist, etc)
    # This must happen before orchestration starts.
    ExperimentOrchestrator.validate_config(config)

    # Dependency injection here for orchestrator logic
    execution_id_ref = {"id": ""}

    def _monitoring_cb(
        realization_id: int,
        iteration: int,
        current_status: str,
        step_name: str | None = None,
    ) -> None:
        exec_id = execution_id_ref["id"]
        _update_realization_status(
            execution_id=exec_id,
            iteration=iteration,
            realization_id=realization_id,
            new_status=current_status,
            step_name=step_name,
        )

    _experiment_run_counts[experiment_id] += 1

    # Generate API URL. Default to localhost for now.
    # In a real cluster environment, this would need to be
    # the externally reachable host.
    api_url = "http://localhost:8000"

    orchestrator = ExperimentOrchestrator(
        config=config,
        experiment_id=experiment_id,
        monitoring_callback=_monitoring_cb,
        run_count=_experiment_run_counts[experiment_id],
        api_url=api_url,
    )

    execution_id = orchestrator.execution_id
    execution_id_ref["id"] = execution_id
    _executions_to_configs[execution_id] = config
    _latest_execution_id[experiment_id] = execution_id
    _active_orchestrators[execution_id] = orchestrator
    # Explicitly initialize status storage for this execution
    if execution_id not in _experiment_statuses:
        _experiment_statuses[execution_id] = defaultdict(dict)

    _execution_states[execution_id] = ExecutionState(
        experiment_id=experiment_id,
        execution_id=execution_id,
        status="RUNNING",
    )

    async def _run_wrapped() -> None:
        try:
            await orchestrator.run_experiment()
            _execution_states[execution_id] = ExecutionState(
                experiment_id=experiment_id,
                execution_id=execution_id,
                status="COMPLETED",
            )
        except Exception:
            error_msg = traceback.format_exc()
            _execution_states[execution_id] = ExecutionState(
                experiment_id=experiment_id,
                execution_id=execution_id,
                status="FAILED",
                error=error_msg,
            )
            # Make sure it gets printed on the server side as well
            logger.exception("Background execution failed")
        finally:
            _active_orchestrators.pop(execution_id, None)

    # 1. Execute the orchestrator loop strictly in the background (Fire and Forget)
    task = asyncio.create_task(_run_wrapped())
    _consolidation_tasks.add(task)
    task.add_done_callback(_consolidation_tasks.discard)

    # The orchestrator will spawn consolidation workers for each iteration.

    # Allow a microscopic tick for PENDING statuses to be emitted via callback
    await asyncio.sleep(0.05)
    return {"execution_id": execution_id, "iteration": 0}


@router.get(
    "/experiments/{experiment_id}/executions/{execution_id}/state",
    summary="Retrieve execution state",
    description="Returns the overall state of an execution.",
)
async def get_execution_state(
    experiment_id: str,
    execution_id: str,
) -> ExecutionState:
    """Retrieve the overall state of an execution.

    Raises:
        HTTPException: If the execution state is not found.
    """
    _, state = _recover_execution(experiment_id, execution_id)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' state not found",
        )
    return state


@router.get(
    "/experiments/{experiment_id}/status",
    summary="Retrieve latest realization status",
    description="Returns the status of all realizations for the latest "
    "execution of a given experiment ID.",
)
async def get_latest_experiment_status(
    experiment_id: str,
) -> list[RealizationStatus]:
    """Retrieve the status of all realizations for the latest experiment run.

    Raises:
        HTTPException: If the experiment is not found.
    """
    if experiment_id not in _latest_execution_id:
        if experiment_id in _experiment_configs:
            return []
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Experiment '{experiment_id}' not found",
        )

    execution_id = _latest_execution_id[experiment_id]
    all_statuses: list[RealizationStatus] = []
    for iter_dict in _experiment_statuses[execution_id].values():
        all_statuses.extend(iter_dict.values())
    return all_statuses


@router.get(
    "/experiments/{experiment_id}/executions/{execution_id}/status",
    summary="Retrieve specific execution status",
    description="Returns the status of all realizations for a specific execution ID.",
)
async def get_execution_status(
    experiment_id: str,
    execution_id: str,
) -> list[RealizationStatus]:
    """Retrieve the status of all realizations for a specific execution.

    Args:
        experiment_id: The unique experiment ID.
        execution_id: The unique execution ID.

    Raises:
        HTTPException: If the execution is not found.
    """
    config, _ = _recover_execution(experiment_id, execution_id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' not found",
        )

    if execution_id not in _experiment_statuses:
        return []

    all_statuses: list[RealizationStatus] = []
    for iter_dict in _experiment_statuses[execution_id].values():
        all_statuses.extend(iter_dict.values())
    return all_statuses


@router.post(
    "/experiments/{experiment_id}/executions/{execution_id}/ensembles/{iteration}/realizations/{realization_id}/complete",
    summary="Mark realization as complete",
    description="Signals that a realization has finished successfully.",
)
async def mark_realization_complete(
    experiment_id: str,
    execution_id: str,
    iteration: int,
    realization_id: int,
    payload: CompletePayload,
) -> dict[str, str]:
    """Mark a realization as complete.

    Raises:
        HTTPException: If the experiment or execution is not found.
    """
    config, _ = _recover_execution(experiment_id, execution_id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Experiment '{experiment_id}' or execution "
            f"'{execution_id}' not found",
        )

    _update_realization_status(
        execution_id=execution_id,
        iteration=iteration,
        realization_id=realization_id,
        new_status="COMPLETED",
        step_name=payload.source_step,
    )
    if orchestrator := _active_orchestrators.get(execution_id):
        await orchestrator.record_realization_complete(
            iteration,
            realization_id,
            payload.source_step,
        )
    return {"status": "success"}


@router.post(
    "/experiments/{experiment_id}/executions/{execution_id}/ensembles/{iteration}/realizations/{realization_id}/fail",
    summary="Mark realization as failed",
    description="Signals that a realization has encountered an error.",
)
async def mark_realization_failed(
    experiment_id: str,
    execution_id: str,
    iteration: int,
    realization_id: int,
    payload: FailurePayload,
) -> dict[str, str]:
    """Mark a realization as failed.

    Raises:
        HTTPException: If the experiment or execution is not found.
    """
    config, _ = _recover_execution(experiment_id, execution_id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Experiment '{experiment_id}' or execution "
            f"'{execution_id}' not found",
        )

    _update_realization_status(
        execution_id=execution_id,
        iteration=iteration,
        realization_id=realization_id,
        new_status="FAILED",
        step_name=payload.source_step,
    )
    if orchestrator := _active_orchestrators.get(execution_id):
        await orchestrator.record_realization_fail(
            iteration,
            realization_id,
            payload.source_step,
        )
    # TODO(@yngves.kristiansen, #0): In Section 5, store payload.error and  # noqa: FIX002, E501
    # payload.traceback for user inspection
    return {"status": "success"}


def _update_realization_status(
    execution_id: str,
    iteration: int,
    realization_id: int,
    new_status: str,
    step_name: str | None = None,
) -> None:
    """Helper to update the in-memory status of a realization."""
    if execution_id not in _experiment_statuses:
        # We might want to initialize it if we know the config exists,
        # but for now we follow existing patterns.
        return

    state = _experiment_statuses[execution_id][iteration].get(realization_id)
    if not state:
        state = RealizationStatus(
            realization_id=realization_id,
            iteration=iteration,
            status=new_status,
        )
        _experiment_statuses[execution_id][iteration][realization_id] = state

    if step_name:
        step = next((s for s in state.steps if s.name == step_name), None)
        if not step:
            step = StepStatus(name=step_name, status=new_status)
            state.steps.append(step)
        step.status = new_status
        if new_status == "RUNNING" and not step.start_time:
            step.start_time = datetime.now(tz=UTC)
        elif new_status in {"COMPLETED", "FAILED"}:
            step.end_time = datetime.now(tz=UTC)
    else:
        state.status = new_status


@router.post(
    "/experiments/{experiment_id}/executions/{execution_id}/ensembles/{iteration}/realizations/{realization_id}/status",
    summary="Update realization or step status",
    description="Updates the status of a realization or a specific step within it.",
)
async def update_step_status(
    experiment_id: str,
    execution_id: str,
    iteration: int,
    realization_id: int,
    new_status: Annotated[str, Query(alias="status")],
    step_name: Annotated[str | None, Query()] = None,
) -> dict[str, str]:
    """Update the status of a realization or a specific step.

    Raises:
        HTTPException: If the execution is not found.
    """
    _ = experiment_id
    if execution_id not in _experiment_statuses:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' not found",
        )

    state = _experiment_statuses[execution_id][iteration].get(realization_id)
    if not state:
        state = RealizationStatus(
            realization_id=realization_id,
            iteration=iteration,
            status=new_status,
        )
        _experiment_statuses[execution_id][iteration][realization_id] = state

    if step_name:
        step = next((s for s in state.steps if s.name == step_name), None)
        if not step:
            step = StepStatus(name=step_name, status=new_status)
            state.steps.append(step)
        step.status = new_status
        if new_status == "RUNNING" and not step.start_time:
            step.start_time = datetime.now(tz=UTC)
        elif new_status in {"COMPLETED", "FAILED"}:
            step.end_time = datetime.now(tz=UTC)
    else:
        state.status = new_status

    return {"status": "success"}


@router.get(
    "/experiments/{experiment_id}/executions/{execution_id}/ensembles/{iteration}/realizations/{realization_id}/steps/{step_name}/logs",
    summary="Retrieve step execution logs",
    description="Returns the stdout and stderr logs for a specific forward model step.",
)
async def get_step_logs(
    experiment_id: str,
    execution_id: str,
    iteration: int,
    realization_id: int,
    step_name: str,
) -> StepLogResponse:
    """Retrieve logs for a specific forward model step.

    Raises:
        HTTPException: If the experiment or logs are not found.
    """
    config, _ = _recover_execution(experiment_id, execution_id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Experiment '{experiment_id}' not found",
        )

    api = StorageAPI(base_storage_path=config.storage_base)
    try:
        stdout = api.get_step_log(
            config.name,
            execution_id,
            iteration,
            realization_id,
            step_name,
            "stdout",
        )
        stderr = api.get_step_log(
            config.name,
            execution_id,
            iteration,
            realization_id,
            step_name,
            "stderr",
        )
        return StepLogResponse(stdout=stdout, stderr=stderr)
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.post(
    "/experiments/{experiment_id}/executions/{execution_id}/ensembles/{iteration}/ingest",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest data from a forward model",
    description="Appends a payload (responses or parameters) to the ingestion queue.",
)
async def ingest_data(
    experiment_id: str,
    execution_id: str,
    iteration: int,
    payload: IngestionPayload,
) -> dict[str, str]:
    """Ingest payload into the experiment storage queue.

    Raises:
        HTTPException: If the experiment is not found.
    """
    config, _ = _recover_execution(experiment_id, execution_id)

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Experiment '{experiment_id}' or execution "
            f"'{execution_id}' not found",
        )

    receiver = IngestionReceiver(base_storage_path=config.storage_base)
    receiver.receive(
        experiment_id=config.name,
        execution_id=execution_id,
        iteration=iteration,
        payload=payload,
    )
    return {"status": "success"}


@router.get(
    "/experiments/{experiment_id}/executions/{execution_id}/ensembles/{iteration}/parameters",
    summary="Retrieve parameter matrix",
    description="Returns the parameter matrix for a given execution and iteration.",
)
async def get_parameters(
    experiment_id: str,
    execution_id: str,
    iteration: int,
) -> list[dict[str, Any]]:
    """Retrieve the parameter matrix as a list of dictionaries.

    Raises:
        HTTPException: If the experiment is not found.
    """
    config, _ = _recover_execution(experiment_id, execution_id)

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Experiment '{experiment_id}' not found",
        )

    api = StorageAPI(base_storage_path=config.storage_base)
    try:
        df = api.get_parameters(
            experiment_id=config.name,
            execution_id=execution_id,
            iteration=iteration,
        )
        return df.to_dicts()
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.get(
    "/experiments/{experiment_id}/executions/{execution_id}/ensembles/{iteration}/responses",
    summary="Retrieve consolidated responses",
    description="Returns all consolidated responses for a given execution "
    "and iteration.",
)
async def get_responses(
    experiment_id: str,
    execution_id: str,
    iteration: int,
) -> list[dict[str, Any]]:
    """Retrieve consolidated responses as a list of dictionaries.

    Raises:
        HTTPException: If the experiment or data is not found.
    """
    config, _ = _recover_execution(experiment_id, execution_id)

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Experiment '{experiment_id}' or execution "
            f"'{execution_id}' not found",
        )

    api = StorageAPI(base_storage_path=config.storage_base)
    try:
        df = api.get_responses(
            experiment_id=config.name,
            execution_id=execution_id,
            iteration=iteration,
        )
        return df.to_dicts()
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
