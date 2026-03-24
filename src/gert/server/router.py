"""API router for GERT server."""

import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi import Path as FastApiPath
from pydantic import BaseModel, Field

from gert.experiment_runner.experiment_orchestrator import ExperimentOrchestrator
from gert.experiment_runner.job_submitter import JobSubmitter
from gert.experiment_runner.realization_workdir_manager import RealizationWorkdirManager
from gert.experiments.models import ExperimentConfig, IngestionPayload
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
    orchestrator = ExperimentOrchestrator(job_submitter, workdir_manager)

    new_id = orchestrator.start_experiment(config)
    orchestrator.run_iteration(iteration=0, parameters=config.parameter_matrix)

    return {"status": "started", "experiment_id": new_id}


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
