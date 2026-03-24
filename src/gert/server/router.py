"""API router for GERT server."""

import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi import Path as FastApiPath
from pydantic import BaseModel, Field

from gert.experiment_runner.experiment_orchestrator import ExperimentOrchestrator
from gert.experiment_runner.job_submitter import JobSubmitter
from gert.experiment_runner.realization_workdir_manager import RealizationWorkdirManager
from gert.experiments.models import ExperimentConfig, IngestionPayload
from gert.server.monitoring import RealizationStatus, monitoring_service
from gert.storage.consolidation import ConsolidationWorker
from gert.storage.ingestion import IngestionReceiver
from gert.storage.query import StorageQueryAPI

router = APIRouter(tags=["experiments"])


class ExperimentResponse(BaseModel):
    """Response model for a newly created experiment."""

    id: str = Field(..., description="The unique experiment ID.")


# In-memory storage for experiment configurations (Mocked storage)
# In PR 2.1, this should move to a more persistent storage backend.
_experiment_configs: dict[str, ExperimentConfig] = {}


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
    "/experiments/{id}/config",
    summary="Retrieve experiment configuration",
    description="Returns the immutable configuration for a given experiment ID.",
)
async def get_experiment_config(
    experiment_id: Annotated[
        str,
        FastApiPath(
            alias="id",
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


@router.post(
    "/experiments/{id}/start",
    summary="Start experiment",
    description="Launches the orchestration loop for a previously "
    "registered experiment.",
)
async def start_experiment(
    experiment_id: Annotated[str, FastApiPath(alias="id")],
) -> dict[str, str]:
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
    # Dependency injection here for orchestrator logic
    job_submitter = JobSubmitter(
        queue_config=config.queue_config.custom_attributes,
        executor_type=config.queue_config.backend,
    )
    workdir_manager = RealizationWorkdirManager(BASE_STORAGE_PATH / "workdirs")

    execution_id_ref = {"id": ""}

    def _monitoring_cb(
        realization_id: int,
        iteration: int,
        current_status: str,
    ) -> None:
        monitoring_service.update_status(
            experiment_id=execution_id_ref["id"],
            realization_id=realization_id,
            iteration=iteration,
            status=current_status,
        )

    orchestrator = ExperimentOrchestrator(
        job_submitter,
        workdir_manager,
        monitoring_callback=_monitoring_cb,
    )
    new_id = orchestrator.start_experiment(config)
    execution_id_ref["id"] = new_id

    # Initialize statuses as PENDING
    # Determine unique realizations
    realizations: set[int] = set()
    if config.parameter_matrix.values:
        for payload in config.parameter_matrix.values.values():
            realizations.update(payload.keys())

    for r_id in realizations:
        monitoring_service.update_status(new_id, r_id, 0, "PENDING")

    orchestrator.run_iteration(iteration=0, parameters=config.parameter_matrix)

    return {"status": "started", "experiment_id": new_id}


@router.get(
    "/experiments/{id}/status",
    summary="Get execution status",
    description="Returns the execution status of all realizations for an experiment.",
)
async def get_experiment_status(
    experiment_id: Annotated[str, FastApiPath(alias="id")],
) -> list[RealizationStatus]:
    """Get the current execution status."""
    return monitoring_service.get_experiment_status(experiment_id)


@router.websocket("/experiments/{id}/monitor")
async def monitor_experiment(
    websocket: WebSocket,
    experiment_id: Annotated[str, FastApiPath(alias="id")],
) -> None:
    """Real-time monitoring via WebSocket."""
    await websocket.accept()
    queue = await monitoring_service.subscribe(experiment_id)

    # Send initial state
    initial_states = monitoring_service.get_experiment_status(experiment_id)
    for state in initial_states:
        await websocket.send_json(state.model_dump())

    try:
        while True:
            state = await queue.get()
            await websocket.send_json(state.model_dump())
    except WebSocketDisconnect:
        monitoring_service.unsubscribe(experiment_id, queue)


# Storage Dependencies
# In a real app, these would be configured via app state or a settings object.
BASE_STORAGE_PATH = Path("./gert_storage")


def get_ingestion_receiver() -> IngestionReceiver:
    """Dependency provider for IngestionReceiver."""
    return IngestionReceiver(BASE_STORAGE_PATH)


def get_consolidation_worker() -> ConsolidationWorker:
    """Dependency provider for ConsolidationWorker."""
    return ConsolidationWorker(BASE_STORAGE_PATH)


def get_query_api() -> StorageQueryAPI:
    """Dependency provider for StorageQueryAPI."""
    return StorageQueryAPI(BASE_STORAGE_PATH)


@router.post(
    "/storage/{id}/ingest",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest data",
    description="Pushes a simulated response or parameter payload into the queue.",
)
async def ingest_data(
    experiment_id: Annotated[str, FastApiPath(alias="id")],
    payload: IngestionPayload,
    receiver: Annotated[IngestionReceiver, Depends(get_ingestion_receiver)],
) -> dict[str, str]:
    """Ingest a payload for a given experiment."""
    receiver.receive(experiment_id, payload)

    last_name = None
    last_value = None
    if hasattr(payload, "key") and hasattr(payload, "value"):
        key = payload.key
        if isinstance(key, dict):
            last_name = ", ".join(f"{k}={v}" for k, v in key.items())
        else:
            last_name = str(key)

        val = payload.value
        last_value = str(val.path) if hasattr(val, "path") else str(val)

    monitoring_service.increment_responses(
        experiment_id,
        payload.realization,
        last_response_name=last_name,
        last_response_value=last_value,
    )
    return {"status": "accepted"}


@router.get(
    "/storage/{id}/responses",
    summary="Retrieve responses",
    description="Returns all consolidated responses for the experiment.",
)
async def get_responses(
    experiment_id: Annotated[str, FastApiPath(alias="id")],
    query_api: Annotated[StorageQueryAPI, Depends(get_query_api)],
    worker: Annotated[ConsolidationWorker, Depends(get_consolidation_worker)],
) -> list[dict[str, Any]]:
    """Retrieve consolidated responses, triggering a consolidation first.

    Raises:
        HTTPException: If the experiment is not found.
    """
    # For now, we trigger consolidation on every read to ensure fresh data.
    # In a production system, this would be a background task.
    worker.consolidate(experiment_id)

    try:
        df = query_api.get_responses(experiment_id)
        return df.to_dicts()
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
