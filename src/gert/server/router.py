"""API router for GERT server."""

import asyncio
import uuid
from collections import defaultdict
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    HTTPException,
    status,
)
from fastapi import Path as FastApiPath
from pydantic import BaseModel, Field

from gert.experiment_runner.experiment_orchestrator import ExperimentOrchestrator
from gert.experiments.models import ExperimentConfig, IngestionPayload
from gert.storage.api import StorageAPI
from gert.storage.ingestion import IngestionReceiver

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
    # Dependency injection here for orchestrator logic
    execution_id_ref = {"id": ""}

    def _monitoring_cb(
        realization_id: int,
        iteration: int,
        current_status: str,
    ) -> None:
        exec_id = execution_id_ref["id"]
        state = _experiment_statuses[exec_id].get(realization_id)
        if state:
            state.status = current_status
            state.iteration = iteration
        else:
            _experiment_statuses[exec_id][realization_id] = RealizationStatus(
                realization_id=realization_id,
                iteration=iteration,
                status=current_status,
            )

    _experiment_run_counts[experiment_id] += 1
    orchestrator = ExperimentOrchestrator(
        config=config,
        experiment_id=experiment_id,
        monitoring_callback=_monitoring_cb,
        run_count=_experiment_run_counts[experiment_id],
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
    return list(_experiment_statuses[execution_id].values())


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

    return list(_experiment_statuses[execution_id].values())


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
