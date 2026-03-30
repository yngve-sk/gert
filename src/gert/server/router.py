"""API router for GERT server."""

import asyncio
import uuid
from collections import defaultdict
from datetime import UTC, datetime
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
from gert.experiments.models import ExperimentConfig, IngestionPayload
from gert.storage.api import StorageAPI
from gert.storage.ingestion import IngestionReceiver

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


# In-memory storage for experiment configurations (Mocked storage)
# In PR 2.1, this should move to a more persistent storage backend.
_experiment_configs: dict[str, ExperimentConfig] = {}
_executions_to_configs: dict[str, ExperimentConfig] = {}
_experiment_statuses: dict[
    str,
    dict[int, dict[int, RealizationStatus]],
] = defaultdict(lambda: defaultdict(dict))
_consolidation_tasks: set[asyncio.Task[Any]] = set()
_experiment_run_counts: dict[str, int] = defaultdict(int)
_latest_execution_id: dict[str, str] = {}


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
    return ExperimentResponse(id=experiment_id)


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

    # Calculate realizations from parameter matrix
    realizations: set[int] = set()
    for param_values in config.parameter_matrix.values.values():
        realizations.update(param_values.keys())

    num_realizations = len(realizations)
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
        # Use (iteration, realization_id) as the key to support multi-step workflows
        state = _experiment_statuses[exec_id][iteration].get(realization_id)
        if not state:
            state = RealizationStatus(
                realization_id=realization_id,
                iteration=iteration,
                status=current_status,
            )
            _experiment_statuses[exec_id][iteration][realization_id] = state

        if step_name:
            # Update specific step status
            step = next((s for s in state.steps if s.name == step_name), None)
            if not step:
                step = StepStatus(name=step_name, status=current_status)
                state.steps.append(step)

            step.status = current_status
            if current_status == "RUNNING" and not step.start_time:
                step.start_time = datetime.now(tz=UTC)
            elif current_status in {"COMPLETED", "FAILED"}:
                step.end_time = datetime.now(tz=UTC)

        else:
            # Update overall realization status
            state.status = current_status

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

    # 1. Execute the orchestrator loop strictly in the background (Fire and Forget)
    task = asyncio.create_task(orchestrator.run_experiment())
    _consolidation_tasks.add(task)
    task.add_done_callback(_consolidation_tasks.discard)

    # The orchestrator will spawn consolidation workers for each iteration.

    # Allow a microscopic tick for PENDING statuses to be emitted via callback
    await asyncio.sleep(0.05)
    return {"execution_id": execution_id, "iteration": 0}


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
    _ = experiment_id  # Unused in current implementation
    if execution_id not in _experiment_statuses:
        if execution_id in _executions_to_configs:
            return []
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' not found",
        )

    all_statuses: list[RealizationStatus] = []
    for iter_dict in _experiment_statuses[execution_id].values():
        all_statuses.extend(iter_dict.values())
    return all_statuses


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
    config = _experiment_configs.get(experiment_id)
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
    # Resolve experiment_id to config
    config = _experiment_configs.get(experiment_id)

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Experiment '{experiment_id}' not found",
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
    # Resolve experiment_id to config
    config = _experiment_configs.get(experiment_id)

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Experiment '{experiment_id}' not found",
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
