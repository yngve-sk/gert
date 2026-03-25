"""API router for GERT server."""

import asyncio
import uuid
from collections import defaultdict
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
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


class RealizationStatus(BaseModel):
    """Status of a specific realization execution."""

    realization_id: int
    iteration: int
    status: str


class ExperimentResponse(BaseModel):
    """Response model for a newly created experiment."""

    id: str = Field(..., description="The unique experiment ID.")


# In-memory storage for experiment configurations (Mocked storage)
# In PR 2.1, this should move to a more persistent storage backend.
_experiment_configs: dict[str, ExperimentConfig] = {}
_executions_to_configs: dict[str, ExperimentConfig] = {}
_experiment_statuses: dict[str, dict[int, RealizationStatus]] = defaultdict(dict)
_consolidation_tasks: set[asyncio.Task[Any]] = set()


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
    workdir_manager = RealizationWorkdirManager(config.realization_workdirs_base)

    execution_id_ref = {"id": ""}

    def _monitoring_cb(
        realization_id: int,
        iteration: int,
        current_status: str,
    ) -> None:
        exp_id = execution_id_ref["id"]
        state = _experiment_statuses[exp_id].get(realization_id)
        if state:
            state.status = current_status
            state.iteration = iteration
        else:
            _experiment_statuses[exp_id][realization_id] = RealizationStatus(
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
    _executions_to_configs[new_id] = config

    # Initialize statuses as PENDING
    # Determine unique realizations
    realizations: set[int] = set()
    if config.parameter_matrix.values:
        for payload in config.parameter_matrix.values.values():
            realizations.update(payload.keys())

    for r_id in realizations:
        _experiment_statuses[new_id][r_id] = RealizationStatus(
            realization_id=r_id,
            iteration=0,
            status="PENDING",
        )

    orchestrator.run_iteration(iteration=0, parameters=config.parameter_matrix)

    async def _consolidation_loop() -> None:
        """Background task to periodically consolidate responses."""
        worker = ConsolidationWorker(config.storage_base)
        while True:
            await asyncio.sleep(config.consolidation_interval)
            worker.consolidate(new_id)

            statuses = _experiment_statuses.get(new_id)
            if statuses and all(
                s.status in {"COMPLETED", "FAILED"} for s in statuses.values()
            ):
                # Do one final consolidation to ensure nothing is missed
                worker.consolidate(new_id)
                break

    task = asyncio.create_task(_consolidation_loop())
    _consolidation_tasks.add(task)
    task.add_done_callback(_consolidation_tasks.discard)

    ensemble_id = uuid.uuid5(uuid.UUID(new_id), "0").hex
    return {"status": "started", "experiment_id": new_id, "ensemble_id": ensemble_id}


@router.get(
    "/experiments/{id}/status",
    summary="Get execution status",
    description="Returns the execution status of all realizations for an experiment.",
)
async def get_experiment_status(
    experiment_id: Annotated[str, FastApiPath(alias="id")],
) -> list[RealizationStatus]:
    """Get the current execution status."""
    return list(_experiment_statuses[experiment_id].values())


# Storage Dependencies
def get_experiment_config_dependency(
    experiment_id: Annotated[str, FastApiPath(alias="id")],
) -> ExperimentConfig:
    """Dependency to retrieve an experiment configuration by ID.

    Raises:
        HTTPException: If the experiment is not found.
    """
    if experiment_id in _experiment_configs:
        return _experiment_configs[experiment_id]
    if experiment_id in _executions_to_configs:
        return _executions_to_configs[experiment_id]
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Experiment '{experiment_id}' not found",
    )


def get_ingestion_receiver(
    config: Annotated[ExperimentConfig, Depends(get_experiment_config_dependency)],
) -> IngestionReceiver:
    """Dependency provider for IngestionReceiver."""
    return IngestionReceiver(config.storage_base)


def get_consolidation_worker(
    config: Annotated[ExperimentConfig, Depends(get_experiment_config_dependency)],
) -> ConsolidationWorker:
    """Dependency provider for ConsolidationWorker."""
    return ConsolidationWorker(config.storage_base)


def get_query_api(
    config: Annotated[ExperimentConfig, Depends(get_experiment_config_dependency)],
) -> StorageQueryAPI:
    """Dependency provider for StorageQueryAPI."""
    return StorageQueryAPI(config.storage_base)


@router.post(
    "/storage/{id}/ensembles/{ensemble_id}/ingest",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest data",
    description="Pushes a simulated response or parameter payload into the queue.",
)
async def ingest_data(
    experiment_id: Annotated[str, FastApiPath(alias="id")],
    ensemble_id: str,
    payload: IngestionPayload,
    receiver: Annotated[IngestionReceiver, Depends(get_ingestion_receiver)],
) -> dict[str, str]:
    """Ingest a payload for a given experiment and ensemble."""
    receiver.receive(experiment_id, ensemble_id, payload)
    return {"status": "accepted"}


@router.get(
    "/storage/{id}/ensembles/{ensemble_id}/responses",
    summary="Retrieve responses",
    description="Returns all consolidated responses for the experiment and ensemble.",
)
async def get_responses(
    experiment_id: Annotated[str, FastApiPath(alias="id")],
    ensemble_id: str,
    query_api: Annotated[StorageQueryAPI, Depends(get_query_api)],
) -> list[dict[str, Any]]:
    """Retrieve consolidated responses.

    Raises:
        HTTPException: If the experiment or ensemble is not found.
    """
    try:
        df = query_api.get_responses(experiment_id, ensemble_id)
        return df.to_dicts()
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
