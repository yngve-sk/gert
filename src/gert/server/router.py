"""API router for GERT server."""

import asyncio
import io
import json
import logging
import shutil
import traceback
from collections import defaultdict
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, cast

import anyio
from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi import Path as FastApiPath
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from gert.experiment_runner.experiment_orchestrator import ExperimentOrchestrator
from gert.experiments.models import (
    ExecutionState,
    ExperimentConfig,
    IngestionPayload,
    ObservationSummary,
    UpdateMetadata,
)
from gert.server.models import ConnectionInfo, SystemInfo
from gert.storage.api import StorageAPI
from gert.storage.ingestion import IngestionReceiver

logger = logging.getLogger(__name__)

router = APIRouter(tags=["experiments"])

SERVER_START_TIME = datetime.now(UTC).isoformat()


@router.get("/health", summary="Healthcheck endpoint")
async def health_check() -> dict[str, str]:
    """Return a simple OK status."""
    return {"status": "ok"}


@router.get(
    "/connection-info",
    summary="Get server connection information",
    description="Returns the connection details for this GERT server instance.",
)
async def get_connection_info(request: Request) -> ConnectionInfo:
    """Return the server's connection information.

    Raises:
        HTTPException: if connection information is not available.
    """
    if (
        not hasattr(request.app.state, "connection_info")
        or not request.app.state.connection_info
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Connection info not yet available.",
        )
    return cast("ConnectionInfo", request.app.state.connection_info)


@router.get(
    "/system/info",
    summary="Get general system information",
    description="Returns version, server URL, start time, and aggregate metrics.",
)
async def get_system_info(request: Request) -> SystemInfo:
    """Return general system information."""
    if (
        not hasattr(request.app.state, "connection_info")
        or not request.app.state.connection_info
    ):
        # Fallback for when connection info isn't fully set yet
        base_url = str(request.base_url)
        version = "0.1.0"
    else:
        conn = cast("ConnectionInfo", request.app.state.connection_info)
        base_url = conn.base_url
        version = conn.version

    state = ServerState.get()

    # Calculate unique experiments (both in-memory and on disk)
    # We can reuse some logic from list_experiments but more concisely
    api = StorageAPI(base_storage_path=Path("./permanent_storage"))
    stored = api.list_experiments()
    all_exp_ids = set(state.configs.keys()) | {exp_id for exp_id, _ in stored}

    active_executions = [
        e for e in state.executions.values() if e.overarching_status == "RUNNING"
    ]

    return SystemInfo(
        version=version,
        server_url=base_url,
        start_time=SERVER_START_TIME,
        num_experiments=len(all_exp_ids),
        num_active_executions=len(active_executions),
        total_events=state.total_events,
    )


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


class StateRecoveryError(Exception):
    """Raised when an execution state cannot be reliably recovered."""


class ExecutionData:
    """Wrapper holding an execution's config, state, and realtime statuses."""

    def __init__(self, config: ExperimentConfig) -> None:
        self.config = config
        self.statuses: dict[int, dict[int, RealizationStatus]] = defaultdict(dict)
        self.orchestrator: ExperimentOrchestrator | None = None
        self.overarching_status: str = "RUNNING"
        self.error: str | None = None
        self.log_handler: logging.Handler | None = None


class ServerState:
    """Singleton holding in-memory server state."""

    _instance: "ServerState | None" = None

    @classmethod
    def get(cls) -> "ServerState":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self.configs: dict[str, ExperimentConfig] = {}
        self.executions: dict[str, ExecutionData] = {}
        self.experiment_executions: dict[str, list[str]] = defaultdict(list)
        self.consolidation_tasks: set[asyncio.Task[Any]] = set()
        self.experiment_run_counts: dict[str, int] = defaultdict(int)
        self.latest_execution_id: dict[str, str] = {}
        self.total_events: int = 0

    def clear(self) -> None:
        """Clear all in-memory state (useful for testing)."""
        self.configs.clear()
        self.executions.clear()
        self.experiment_executions.clear()
        self.consolidation_tasks.clear()
        self.experiment_run_counts.clear()
        self.latest_execution_id.clear()
        self.total_events = 0


def _rebuild_state_from_log(
    experiment_id: str,
    execution_id: str,
    config: ExperimentConfig,
) -> bool:
    """Rebuild the execution statuses strictly from the event log.

    Raises:
        StateRecoveryError: If unable to reconstruct execution status.
    """
    base = Path(config.base_working_directory) / config.storage_base
    events_file = base / experiment_id / execution_id / "status_events.jsonl"
    if not events_file.exists():
        return False

    server_state = ServerState.get()

    if execution_id not in server_state.executions:
        server_state.executions[execution_id] = ExecutionData(config)
        if execution_id not in server_state.experiment_executions[experiment_id]:
            server_state.experiment_executions[experiment_id].append(execution_id)
    else:
        server_state.executions[execution_id].statuses.clear()

    exec_data = server_state.executions[execution_id]

    try:
        with events_file.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                event = json.loads(line)

                iteration = event["iteration"]
                r_id = event["realization_id"]
                st = event["status"]

                # Check for overarching execution status events (iteration == -1)
                if iteration == -1 and r_id == -1:
                    exec_data.overarching_status = st
                    exec_data.error = event.get("error")
                    continue

                # Apply to in-memory _experiment_statuses
                _apply_status_event(
                    execution_id,
                    iteration,
                    r_id,
                    st,
                    event.get("step_name"),
                    event.get("timestamp"),
                )
    except Exception as e:
        msg = f"Failed to parse status_events.jsonl {events_file}: {e}"
        raise StateRecoveryError(msg) from e

    return True


def _recover_execution(
    experiment_id: str,
    execution_id: str,
) -> ExperimentConfig | None:
    """Recover execution configuration and log from persistent storage if missing.

    Raises:
        StateRecoveryError: If unable to reconstruct execution status.
    """
    server_state = ServerState.get()

    if execution_id in server_state.executions:
        exec_data = server_state.executions[execution_id]
        return exec_data.config

    config: ExperimentConfig | None = server_state.configs.get(experiment_id)

    # Use the config's storage base if we have it, otherwise fallback to default
    base = config.storage_base if config else Path("./permanent_storage")

    # Recover config first if we don't have it
    if not config:
        config_file = base / experiment_id / "config.json"
        if config_file.exists():
            try:
                config = ExperimentConfig.model_validate_json(
                    config_file.read_text(encoding="utf-8"),
                )
                server_state.configs[experiment_id] = config
            except Exception as e:
                msg = f"Failed to load experiment config {config_file}: {e}"
                raise StateRecoveryError(msg) from e

    if not config:
        return None

    # Rebuild state from event sourcing log
    exists = _rebuild_state_from_log(experiment_id, execution_id, config)

    if exists:
        return config

    return None


@router.get(
    "/experiments",
    summary="List all experiments",
    description="Returns a list of all registered experiment configurations.",
)
def list_experiments() -> list[dict[str, str]]:
    """List all registered experiments."""
    # Start with in-memory ones
    server_state = ServerState.get()
    experiments = [{"id": k, "name": v.name} for k, v in server_state.configs.items()]

    # Add from storage if not already there
    api = StorageAPI(base_storage_path=Path("./permanent_storage"))
    stored = api.list_experiments()

    seen_ids = {e["id"] for e in experiments}
    for exp_id, exp_name in stored:
        if exp_id not in seen_ids:
            experiments.append({"id": exp_id, "name": exp_name})

    return experiments


@router.post(
    "/experiments",
    status_code=status.HTTP_201_CREATED,
    summary="Create a new experiment",
    description="Registers an immutable experiment configuration and returns an ID.",
)
async def create_experiment(
    config: ExperimentConfig,
    experiment_id_override: Annotated[str | None, Query(alias="id")] = None,
) -> ExperimentResponse:
    """Create a new experiment configuration."""
    experiment_id = experiment_id_override or config.name
    ServerState.get().configs[experiment_id] = config

    # Save config to storage
    api = StorageAPI(
        base_storage_path=Path(config.base_working_directory) / config.storage_base,
    )
    api.write_experiment_config(config, experiment_id=experiment_id)

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
    config = _recover_execution(experiment_id, execution_id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' not found",
        )

    server_state = ServerState.get()
    exec_data = server_state.executions.get(execution_id)
    if exec_data and exec_data.orchestrator:
        exec_data.orchestrator.pause(force=force)
    elif exec_data and exec_data.overarching_status not in {
        "PAUSED",
        "COMPLETED",
        "FAILED",
    }:
        _update_realization_status(execution_id, -1, -1, "PAUSED")

    return {"status": "success"}


@router.post(
    "/experiments/{experiment_id}/executions/{execution_id}/resume",
    summary="Resume execution",
    description="Reads the state from permanent storage and resumes the orchestrator.",
)
async def resume_execution(  # noqa: C901
    experiment_id: str,
    execution_id: str,
    request: Request,
) -> dict[str, str]:
    """Resume a paused or crashed execution.

    Raises:
        HTTPException: if the resume request is invalid.
    """
    config = _recover_execution(experiment_id, execution_id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' not found",
        )

    server_state = ServerState.get()
    exec_data = server_state.executions.get(execution_id)
    if exec_data and exec_data.orchestrator:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Execution '{execution_id}' is already running",
        )

    if exec_data and exec_data.overarching_status in {"COMPLETED", "FAILED"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot resume execution in state {exec_data.overarching_status}",
        )

    api_url = str(request.base_url).rstrip("/")

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

    orchestrator = ExperimentOrchestrator(
        config=config,
        experiment_id=experiment_id,
        monitoring_callback=_monitoring_cb,
        api_url=api_url,
        execution_id=execution_id,
    )

    if not exec_data:
        exec_data = ExecutionData(config)
        server_state.executions[execution_id] = exec_data
        if execution_id not in server_state.experiment_executions[experiment_id]:
            server_state.experiment_executions[experiment_id].append(execution_id)

    exec_data.orchestrator = orchestrator
    _update_realization_status(execution_id, -1, -1, "RUNNING")

    # Set up execution-specific logging
    base = Path(config.base_working_directory) / config.storage_base
    exec_dir = base / experiment_id / execution_id
    exec_dir.mkdir(parents=True, exist_ok=True)
    exec_log_file = exec_dir / "execution.log"

    handler = logging.FileHandler(exec_log_file, mode="a")
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s")
    handler.setFormatter(formatter)
    logging.getLogger().addHandler(handler)
    exec_data.log_handler = handler

    async def _run_wrapped() -> None:
        try:
            await orchestrator.run_experiment()
            if orchestrator.is_paused:
                status_str = "PAUSED" if orchestrator.is_force_paused else "PAUSING"
                _update_realization_status(execution_id, -1, -1, status_str)
            else:
                _update_realization_status(execution_id, -1, -1, "COMPLETED")
        except Exception:
            error_msg = traceback.format_exc()
            _update_realization_status(execution_id, -1, -1, "FAILED")
            exec_data.error = error_msg
            logger.exception("Background execution failed")
        finally:
            if exec_data.log_handler:
                logging.getLogger().removeHandler(exec_data.log_handler)
                exec_data.log_handler.close()
                exec_data.log_handler = None
            exec_data.orchestrator = None

    task = asyncio.create_task(_run_wrapped())
    server_state.consolidation_tasks.add(task)
    task.add_done_callback(server_state.consolidation_tasks.discard)

    return {"status": "success"}


@router.get(
    "/experiments/{experiment_id}/executions/{execution_id}/ensembles/{iteration}/manifest",
    summary="Retrieve data manifest",
    description="Lightweight cache-busting endpoint returning timestamps.",
)
def get_manifest(
    experiment_id: str,
    execution_id: str,
    iteration: int,
) -> dict[str, float]:
    """Retrieve the data manifest for an iteration.

    Raises:
        HTTPException: If execution or config not found.
    """
    config = _recover_execution(experiment_id, execution_id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' not found",
        )

    api = StorageAPI(
        base_storage_path=Path(config.base_working_directory) / config.storage_base,
    )
    return api.get_manifest(config.name, execution_id, iteration)


def _ensure_config_loaded(experiment_id: str) -> ExperimentConfig | None:
    """Ensure the experiment config is loaded into memory, fetching if needed."""
    server_state = ServerState.get()
    if experiment_id in server_state.configs:
        return server_state.configs[experiment_id]

    base = Path("./permanent_storage")
    config_file = base / experiment_id / "config.json"
    if config_file.exists():
        try:
            config = ExperimentConfig.model_validate_json(
                config_file.read_text(encoding="utf-8"),
            )
            server_state.configs[experiment_id] = config
        except Exception:
            logger.exception(f"Failed to load experiment config {config_file}")
        else:
            return config
    return None


@router.get(
    "/experiments/{experiment_id}/config",
    summary="Retrieve experiment configuration",
    description="Returns the immutable configuration for a given experiment ID.",
)
def get_experiment_config(
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
    config = _ensure_config_loaded(experiment_id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Experiment '{experiment_id}' not found",
        )
    return config


@router.post(
    "/experiments/{experiment_id}/start",
    summary="Start experiment",
    description="Launches the orchestration loop for a previously "
    "registered experiment.",
)
async def start_experiment(
    experiment_id: str,
    request: Request,
) -> dict[str, Any]:
    """Start an experiment by ID.

    Raises:
        HTTPException: If the experiment is not found.
    """
    server_state = ServerState.get()
    config = _ensure_config_loaded(experiment_id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Experiment '{experiment_id}' not found",
        )

    # Validate environment-specific constraints (executables exist, etc)
    # This must happen before orchestration starts.
    try:
        ExperimentOrchestrator.validate_config(config)
    except Exception as e:
        logger.exception(f"Failed to validate config for experiment {experiment_id}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

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

    server_state.experiment_run_counts[experiment_id] += 1

    # Generate API URL from request
    api_url = str(request.base_url).rstrip("/")

    orchestrator = ExperimentOrchestrator(
        config=config,
        experiment_id=experiment_id,
        monitoring_callback=_monitoring_cb,
        api_url=api_url,
    )

    execution_id = orchestrator.execution_id
    execution_id_ref["id"] = execution_id

    server_state.latest_execution_id[experiment_id] = execution_id

    exec_data = ExecutionData(config)
    exec_data.orchestrator = orchestrator
    exec_data.overarching_status = "RUNNING"

    # Set up execution-specific logging
    base = Path(config.base_working_directory) / config.storage_base
    exec_dir = base / experiment_id / execution_id
    exec_dir.mkdir(parents=True, exist_ok=True)
    exec_log_file = exec_dir / "execution.log"

    global_log = anyio.Path("logs/gert.log")
    if await global_log.exists():
        shutil.copy2("logs/gert.log", exec_log_file)
    else:
        exec_log_file.touch()

    handler = logging.FileHandler(exec_log_file, mode="a")
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s")
    handler.setFormatter(formatter)
    logging.getLogger().addHandler(handler)
    exec_data.log_handler = handler

    server_state.executions[execution_id] = exec_data
    if execution_id not in server_state.experiment_executions[experiment_id]:
        server_state.experiment_executions[experiment_id].append(execution_id)

    async def _run_wrapped() -> None:
        try:
            await orchestrator.run_experiment()

            if getattr(orchestrator, "is_paused", False):
                exec_data.overarching_status = "PAUSED"
                _update_realization_status(execution_id, -1, -1, "PAUSED")
            else:
                exec_data.overarching_status = "COMPLETED"
                _update_realization_status(execution_id, -1, -1, "COMPLETED")

        except Exception:
            error_msg = traceback.format_exc()
            exec_data.overarching_status = "FAILED"
            exec_data.error = error_msg
            _update_realization_status(
                execution_id,
                -1,
                -1,
                "FAILED",
                error_msg=error_msg,
            )
            # Make sure it gets printed on the server side as well
            logger.exception("Background execution failed")
        finally:
            if exec_data.log_handler:
                logging.getLogger().removeHandler(exec_data.log_handler)
                exec_data.log_handler.close()
                exec_data.log_handler = None
            exec_data.orchestrator = None

    # 1. Execute the orchestrator loop strictly in the background (Fire and Forget)
    task = asyncio.create_task(_run_wrapped())
    server_state.consolidation_tasks.add(task)
    task.add_done_callback(server_state.consolidation_tasks.discard)

    # The orchestrator will spawn consolidation workers for each iteration.

    # Allow a microscopic tick for PENDING statuses to be emitted via callback
    await asyncio.sleep(0.05)
    return {"execution_id": execution_id, "iteration": 0}


@router.get(
    "/experiments/{experiment_id}/executions",
    summary="List all executions for an experiment",
    description="Returns a list of all historical and active executions.",
)
def list_executions(
    experiment_id: str,
) -> list[ExecutionState]:
    """List all executions for an experiment.

    Raises:
        HTTPException: If the experiment is not found.
    """
    config = _ensure_config_loaded(experiment_id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Experiment '{experiment_id}' not found",
        )

    exp_dir = config.storage_base / experiment_id
    if not exp_dir.exists():
        return []

    executions = []
    for exec_dir in exp_dir.iterdir():
        if not exec_dir.is_dir():
            continue

        try:
            state = get_execution_state(experiment_id, exec_dir.name)
            executions.append(state)
        except HTTPException:
            continue

    executions.sort(
        key=lambda x: (
            (exp_dir / x.execution_id / "status_events.jsonl").stat().st_mtime
            if (exp_dir / x.execution_id / "status_events.jsonl").exists()
            else 0
        ),
        reverse=True,
    )
    return executions


@router.get(
    "/experiments/{experiment_id}/executions/{execution_id}/state",
    summary="Retrieve execution state",
    description="Returns the overall state of an execution.",
)
def get_execution_state(
    experiment_id: str,
    execution_id: str,
) -> ExecutionState:
    """Retrieve the overall state of an execution.

    Raises:
        HTTPException: If the execution state is not found.
    """
    config = _recover_execution(experiment_id, execution_id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' state not found",
        )

    server_state = ServerState.get()
    exec_data = server_state.executions.get(execution_id)
    if not exec_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' state not found",
        )

    current_iter = max([k for k in exec_data.statuses if k != -1], default=0)

    active = []
    completed = []
    failed = []

    if current_iter in exec_data.statuses:
        for r_id, status_obj in exec_data.statuses[current_iter].items():
            if r_id == -1:
                continue
            if status_obj.status == "COMPLETED":
                completed.append(r_id)
            elif status_obj.status == "ACTIVE":
                active.append(r_id)
            elif status_obj.status == "FAILED":
                failed.append(r_id)

    return ExecutionState(
        experiment_id=experiment_id,
        execution_id=execution_id,
        status=exec_data.overarching_status,
        current_iteration=current_iter,
        active_realizations=active,
        completed_realizations=completed,
        failed_realizations=failed,
        error=exec_data.error,
    )


@router.get(
    "/experiments/{experiment_id}/status",
    summary="Retrieve latest realization status",
    description="Returns the status of all realizations for the latest "
    "execution of a given experiment ID.",
)
def get_latest_experiment_status(
    experiment_id: str,
) -> list[RealizationStatus]:
    """Retrieve the status of all realizations for the latest experiment run.

    Raises:
        HTTPException: If the experiment is not found.
    """
    server_state = ServerState.get()
    if experiment_id not in server_state.latest_execution_id:
        if experiment_id in server_state.configs:
            return []
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Experiment '{experiment_id}' not found",
        )

    execution_id = server_state.latest_execution_id[experiment_id]

    exec_data = server_state.executions.get(execution_id)
    if not exec_data:
        return []

    all_statuses: list[RealizationStatus] = []
    for iter_dict in exec_data.statuses.values():
        all_statuses.extend(iter_dict.values())
    return all_statuses


@router.get(
    "/experiments/{experiment_id}/executions/{execution_id}/status",
    summary="Retrieve specific execution status",
    description="Returns the status of all realizations for a specific execution ID.",
)
def get_execution_status(
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
    config = _recover_execution(experiment_id, execution_id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' not found",
        )

    server_state = ServerState.get()
    exec_data = server_state.executions.get(execution_id)
    if not exec_data:
        return []

    all_statuses: list[RealizationStatus] = []
    for iter_dict in exec_data.statuses.values():
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
    config = _recover_execution(experiment_id, execution_id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' not found",
        )

    _update_realization_status(
        execution_id=execution_id,
        iteration=iteration,
        realization_id=realization_id,
        new_status="COMPLETED",
        step_name=payload.source_step,
    )
    server_state = ServerState.get()
    exec_data = server_state.executions.get(execution_id)
    if exec_data and exec_data.orchestrator:
        await exec_data.orchestrator.record_realization_complete(
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
    config = _recover_execution(experiment_id, execution_id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' not found",
        )

    _update_realization_status(
        execution_id=execution_id,
        iteration=iteration,
        realization_id=realization_id,
        new_status="FAILED",
        step_name=payload.source_step,
    )
    server_state = ServerState.get()
    exec_data = server_state.executions.get(execution_id)
    if exec_data and exec_data.orchestrator:
        await exec_data.orchestrator.record_realization_fail(
            iteration,
            realization_id,
            payload.source_step,
        )
    # TODO(@yngves.kristiansen, #0): In Section 5, store payload.error and  # noqa: FIX002, E501
    # payload.traceback for user inspection
    return {"status": "success"}


def _apply_status_event(
    execution_id: str,
    iteration: int,
    realization_id: int,
    new_status: str,
    step_name: str | None = None,
    timestamp_iso: str | None = None,
) -> None:
    """Helper to apply a status event to the in-memory state."""
    server_state = ServerState.get()
    server_state.total_events += 1

    exec_data = server_state.executions.get(execution_id)
    if not exec_data:
        return

    state = exec_data.statuses[iteration].get(realization_id)
    if not state:
        state = RealizationStatus(
            realization_id=realization_id,
            iteration=iteration,
            status=new_status,
        )
        exec_data.statuses[iteration][realization_id] = state

    event_time = (
        datetime.fromisoformat(timestamp_iso) if timestamp_iso else datetime.now(tz=UTC)
    )

    if step_name:
        step = next((s for s in state.steps if s.name == step_name), None)
        if not step:
            step = StepStatus(name=step_name, status=new_status)
            state.steps.append(step)
        step.status = new_status
        if new_status == "RUNNING" and not step.start_time:
            step.start_time = event_time
        elif new_status in {"COMPLETED", "FAILED"}:
            step.end_time = event_time
    else:
        state.status = new_status


def _update_realization_status(
    execution_id: str,
    iteration: int,
    realization_id: int,
    new_status: str,
    step_name: str | None = None,
    error_msg: str | None = None,
) -> None:
    """Helper to update the in-memory status of a realization and append to disk log."""
    server_state = ServerState.get()
    exec_data = server_state.executions.get(execution_id)
    if not exec_data:
        return

    now_iso = datetime.now(tz=UTC).isoformat()
    _apply_status_event(
        execution_id,
        iteration,
        realization_id,
        new_status,
        step_name,
        now_iso,
    )

    # Also apply to the main ExecutionState wrapper logic
    if iteration == -1 and realization_id == -1:
        exec_data.overarching_status = new_status
        if error_msg:
            exec_data.error = error_msg

    # Append to disk log
    experiment_id = exec_data.config.name
    if exec_data.config:
        base = (
            Path(exec_data.config.base_working_directory)
            / exec_data.config.storage_base
        )
    else:
        base = Path("./permanent_storage")

    events_file = base / experiment_id / execution_id / "status_events.jsonl"

    # Ensure parent directory exists.
    events_file.parent.mkdir(parents=True, exist_ok=True)

    event = {
        "timestamp": now_iso,
        "iteration": iteration,
        "realization_id": realization_id,
        "status": new_status,
        "step_name": step_name,
    }
    if error_msg:
        event["error"] = error_msg
    try:
        with events_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except Exception:
        logger.exception("Failed to write status event to disk")


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
    """Update the status of a realization or a specific step."""
    _ = experiment_id

    _update_realization_status(
        execution_id,
        iteration,
        realization_id,
        new_status,
        step_name,
    )

    server_state = ServerState.get()
    exec_data = server_state.executions.get(execution_id)
    if exec_data and exec_data.orchestrator:
        if new_status == "COMPLETED":
            await exec_data.orchestrator.record_realization_complete(
                iteration,
                realization_id,
                step_name,
            )
        elif new_status == "FAILED":
            await exec_data.orchestrator.record_realization_fail(
                iteration,
                realization_id,
                step_name,
            )

    return {"status": "success"}


@router.get(
    "/experiments/{experiment_id}/executions/{execution_id}/ensembles/{iteration}/realizations/{realization_id}/steps/{step_name}/logs",
    summary="Retrieve step execution logs",
    description="Returns the stdout and stderr logs for a specific forward model step.",
)
def get_step_logs(
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
    config = _recover_execution(experiment_id, execution_id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' not found",
        )

    api = StorageAPI(
        base_storage_path=Path(config.base_working_directory) / config.storage_base,
    )
    try:
        stdout = api.get_step_log(
            experiment_id,
            execution_id,
            iteration,
            realization_id,
            step_name,
            "stdout",
        )
        stderr = api.get_step_log(
            experiment_id,
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
    config = _recover_execution(experiment_id, execution_id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' not found",
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
    summary="Retrieve parameter matrix as Parquet stream",
    description="Returns the parameter matrix for a given execution and iteration. "
    "You can request JSON using Accept: application/json.",
    response_model=None,
    responses={
        200: {
            "content": {
                "application/vnd.apache.parquet": {},
                "application/json": {},
            },
            "description": "The parameter matrix in Parquet or JSON format.",
        },
    },
)
def get_parameters(
    experiment_id: str,
    execution_id: str,
    iteration: int,
    request: Request,
) -> StreamingResponse | Response:
    """Retrieve the parameter matrix as a Parquet stream or JSON.

    Raises:
        HTTPException: If the experiment is not found.
    """
    config = _recover_execution(experiment_id, execution_id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' not found",
        )

    api = StorageAPI(
        base_storage_path=Path(config.base_working_directory) / config.storage_base,
    )
    try:
        df = api.get_parameters(
            experiment_id=config.name,
            execution_id=execution_id,
            iteration=iteration,
        )

        accept = request.headers.get("accept", "")
        if "application/json" in accept:
            json_str = df.write_ndjson()
            return Response(content=json_str, media_type="application/x-ndjson")

        buffer = io.BytesIO()
        df.write_parquet(buffer)
        buffer.seek(0)
        return StreamingResponse(
            buffer,
            media_type="application/vnd.apache.parquet",
            headers={
                "Content-Disposition": (
                    f"attachment; filename=parameters_{iteration}.parquet"
                ),
            },
        )
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.get(
    "/experiments/{experiment_id}/executions/{execution_id}/ensembles/{iteration}/responses",
    summary="Retrieve consolidated responses as Parquet stream",
    description="Returns all consolidated responses for a given execution "
    "and iteration. You can request JSON using Accept: application/json.",
    response_model=None,
    responses={
        200: {
            "content": {
                "application/vnd.apache.parquet": {},
                "application/json": {},
            },
            "description": "The consolidated responses in Parquet or JSON format.",
        },
    },
)
def get_responses(
    experiment_id: str,
    execution_id: str,
    iteration: int,
    request: Request,
) -> StreamingResponse | Response:
    """Retrieve consolidated responses.

    Raises:
        HTTPException: If the experiment or data is not found.
    """
    config = _recover_execution(experiment_id, execution_id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' not found",
        )

    api = StorageAPI(
        base_storage_path=Path(config.base_working_directory) / config.storage_base,
    )
    try:
        df = api.get_responses(
            experiment_id=config.name,
            execution_id=execution_id,
            iteration=iteration,
        )

        accept = request.headers.get("accept", "")
        if "application/json" in accept:
            json_str = df.write_ndjson()
            return Response(content=json_str, media_type="application/x-ndjson")

        buffer = io.BytesIO()
        df.write_parquet(buffer)
        buffer.seek(0)
        return StreamingResponse(
            buffer,
            media_type="application/vnd.apache.parquet",
            headers={
                "Content-Disposition": (
                    f"attachment; filename=responses_{iteration}.parquet"
                ),
            },
        )
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.get(
    "/experiments/{experiment_id}/executions/{execution_id}/ensembles/{iteration}/update/metadata",
    summary="Retrieve update metadata",
    description="Returns the metadata for the update that produced this iteration.",
)
def get_update_metadata(
    experiment_id: str,
    execution_id: str,
    iteration: int,
) -> UpdateMetadata:
    """Retrieve the metadata for a mathematical update.

    Raises:
        HTTPException: If execution or config not found.
    """
    config = _recover_execution(experiment_id, execution_id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' not found",
        )

    api = StorageAPI(
        base_storage_path=Path(config.base_working_directory) / config.storage_base,
    )
    try:
        return api.get_update_metadata(
            experiment_id=experiment_id,
            execution_id=execution_id,
            iteration=iteration,
        )
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.get(
    "/experiments/{experiment_id}/executions/{execution_id}/ensembles/{iteration}/observation_summary",
    summary="Retrieve iteration observation summary",
    description="Returns the average deviation statistics for the iteration.",
)
def get_observation_summary(
    experiment_id: str,
    execution_id: str,
    iteration: int,
) -> ObservationSummary | None:
    """Retrieve the observation deviation statistics for an iteration.

    Raises:
        HTTPException: If execution or config not found.
    """
    config = _recover_execution(experiment_id, execution_id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' not found",
        )

    api = StorageAPI(
        base_storage_path=Path(config.base_working_directory) / config.storage_base,
    )
    return api.get_observation_summary(config.name, execution_id, iteration)


@router.websocket("/experiments/{experiment_id}/executions/{execution_id}/events")
async def execution_events_ws(
    websocket: WebSocket,
    experiment_id: str,
    execution_id: str,
) -> None:
    """WebSocket endpoint for live execution status events."""
    await websocket.accept()

    # Simple polling loop to push status
    # In a production system, this would use a proper pubsub broker.
    previous_state_json = ""
    try:
        while True:
            try:
                status_list = get_execution_status(experiment_id, execution_id)
                # Convert to dicts for JSON serialization
                current_state = [s.model_dump(mode="json") for s in status_list]
                current_state_json = json.dumps(current_state)

                # Only send if changed to save bandwidth
                if current_state_json != previous_state_json:
                    await websocket.send_text(current_state_json)
                    previous_state_json = current_state_json

            except HTTPException:
                pass  # Config might not be loaded yet
            except Exception:
                logger.exception("WebSocket error")

            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        pass


@router.get("/experiments/{experiment_id}/executions/{execution_id}/logs/stream")
async def stream_logs(
    request: Request,
    experiment_id: str,
    execution_id: str,
) -> StreamingResponse:
    """Stream application logs via Server-Sent Events (SSE)."""
    config = _recover_execution(experiment_id, execution_id)
    if not config:
        log_file = anyio.Path("logs/gert.log")
    else:
        log_file = anyio.Path(
            Path(config.base_working_directory)
            / config.storage_base
            / experiment_id
            / execution_id
            / "execution.log",
        )

    async def log_generator() -> AsyncGenerator[str]:
        while not await log_file.exists():
            if await request.is_disconnected():
                return
            yield "data: [GERT Server] Waiting for execution to begin logging...\n\n"
            await asyncio.sleep(1.0)

        async with await log_file.open("r", encoding="utf-8") as f:
            yield "data: [GERT] Connected to log stream...\n\n"
            while True:
                if await request.is_disconnected():
                    break
                line = await f.readline()
                if not line:
                    await asyncio.sleep(0.5)
                    continue
                yield f"data: {line.strip()}\n\n"

    return StreamingResponse(
        log_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/experiments/{experiment_id}/executions/{execution_id}/logs")
async def get_execution_logs(
    experiment_id: str,
    execution_id: str,
) -> PlainTextResponse:
    """Retrieve full logs for an execution, either active or finished.

    Raises:
        HTTPException: If the execution or log file is not found.
    """
    config = _recover_execution(experiment_id, execution_id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' not found",
        )

    exec_log = anyio.Path(
        Path(config.base_working_directory)
        / config.storage_base
        / experiment_id
        / execution_id
        / "execution.log",
    )

    if await exec_log.exists():
        return PlainTextResponse(await exec_log.read_text(encoding="utf-8"))

    # Legacy fallback: some older runs might have logs stored as logs/gert.log
    legacy_log = anyio.Path(
        Path(config.base_working_directory)
        / config.storage_base
        / experiment_id
        / "logs"
        / "gert.log",
    )
    if await legacy_log.exists():
        return PlainTextResponse(await legacy_log.read_text(encoding="utf-8"))

    # Fallback to the live global log if all else fails
    live_log = anyio.Path("logs/gert.log")
    if await live_log.exists():
        return PlainTextResponse(await live_log.read_text(encoding="utf-8"))

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Log file not found for this execution",
    )
