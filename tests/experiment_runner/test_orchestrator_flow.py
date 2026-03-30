"""Tests for the ExperimentOrchestrator's macro iteration loop."""

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import polars as pl
import psij
import pytest

from gert.experiment_runner.experiment_orchestrator import ExperimentOrchestrator
from gert.experiment_runner.job_submitter import JobSubmitter
from gert.experiment_runner.realization_workdir_manager import RealizationWorkdirManager
from gert.experiments.models import (
    ExperimentConfig,
    ParameterMatrix,
    QueueConfig,
    UpdateStep,
)
from gert.storage.api import StorageAPI
from gert.updates.base import UpdateAlgorithm


class MockUpdateAlgorithm(UpdateAlgorithm):
    @property
    def name(self) -> str:
        return "mock_algo"

    def perform_update(
        self,
        current_parameters: pl.DataFrame,
        simulated_responses: pl.DataFrame,
        observations: pl.DataFrame,
        updatable_parameter_keys: list[str],
        algorithm_arguments: dict[str, Any],
    ) -> pl.DataFrame:
        # Just return current params unchanged for flow testing
        return current_parameters.clone()


@pytest.fixture
def mock_storage() -> MagicMock:
    return MagicMock(spec=StorageAPI)


@pytest.fixture
def mock_job_submitter() -> MagicMock:
    return MagicMock(spec=JobSubmitter)


@pytest.fixture
def mock_workdir_manager() -> MagicMock:
    return MagicMock(spec=RealizationWorkdirManager)


@pytest.fixture
def orchestrator(
    mock_job_submitter: MagicMock,
    mock_workdir_manager: MagicMock,
    mock_storage: MagicMock,
) -> ExperimentOrchestrator:
    # We mock the internal instantiation by patching
    # but the orchestrator expects a config
    config = ExperimentConfig(
        name="test_exp",
        base_working_directory=Path(),
        forward_model_steps=[],
        queue_config=QueueConfig(backend="local"),
        parameter_matrix=ParameterMatrix(
            values={"p1": {0: 1.0}},  # 1 realization
        ),
        observations=[],
        updates=[
            UpdateStep(name="step1", algorithm="mock_algo"),
        ],
    )
    with (
        patch(
            "gert.experiment_runner.experiment_orchestrator.JobSubmitter",
            return_value=mock_job_submitter,
        ),
        patch(
            "gert.experiment_runner.experiment_orchestrator.RealizationWorkdirManager",
            return_value=mock_workdir_manager,
        ),
        patch(
            "gert.experiment_runner.experiment_orchestrator.StorageAPI",
            return_value=mock_storage,
        ),
    ):
        return ExperimentOrchestrator(config=config, experiment_id="test-exp")


@pytest.mark.asyncio
async def test_run_experiment_loop_flow(
    orchestrator: ExperimentOrchestrator,
    mock_storage: MagicMock,
    mock_job_submitter: MagicMock,
) -> None:
    """Verify that run_experiment executes N+1 iterations and calls updates."""

    # 1. Setup config with 1 update (should run 2 iterations)
    config = ExperimentConfig(
        name="test_exp",
        base_working_directory=Path(),
        forward_model_steps=[],
        queue_config=QueueConfig(backend="local"),
        parameter_matrix=ParameterMatrix(
            values={"p1": {0: 1.0}},  # 1 realization
        ),
        observations=[],
        updates=[
            UpdateStep(name="step1", algorithm="mock_algo"),
        ],
    )

    # 2. Mock storage returns
    mock_storage.get_parameters.return_value = pl.DataFrame(
        {"realization": [0], "p1": [1.0]},
    )
    mock_storage.get_responses.return_value = pl.DataFrame(
        {"realization": [0], "value": [10.0]},
    )

    # 3. Mock plugin discovery
    mock_algo = MockUpdateAlgorithm()

    # To trigger completion, we need to capture the status callback passed to submit
    callbacks: dict[int, Any] = {}

    def side_effect_submit(
        execution_steps: list[str],
        directory: Path,
        status_callback: Any,
    ) -> str:
        it = len(callbacks)
        callbacks[it] = status_callback
        return f"job_{it}"

    mock_job_submitter.submit.side_effect = side_effect_submit

    with patch.object(orchestrator._plugins, "update_algorithms", [mock_algo]):
        task = asyncio.create_task(orchestrator.run_experiment())

        # Wait for Iteration 0 to submit
        while 0 not in callbacks:
            if task.done():
                await task
                pytest.fail("Task finished but iter 0 callback was never set.")
            await asyncio.sleep(0.01)

        # Trigger completion for iter 0
        callbacks[0](MagicMock(spec=psij.Job), psij.JobStatus(psij.JobState.COMPLETED))

        # Wait for Iteration 1 to submit
        while 1 not in callbacks:
            if task.done():
                await task
                pytest.fail("Task finished but iter 1 callback was never set.")
            await asyncio.sleep(0.01)

        # Trigger completion for iter 1
        callbacks[1](MagicMock(spec=psij.Job), psij.JobStatus(psij.JobState.COMPLETED))

        await task

    # Final checks
    assert mock_job_submitter.submit.call_count == 2
    assert mock_storage.flush.call_count == 2
    # Now 2 calls: Initial iteration 0, and after iteration 0 update (for iteration 1)
    assert mock_storage.write_parameters.call_count == 2
    assert 2 not in orchestrator._active_jobs


@pytest.mark.asyncio
async def test_run_experiment_no_updates(
    mock_job_submitter: MagicMock,
    mock_workdir_manager: MagicMock,
    mock_storage: MagicMock,
) -> None:
    """Verify that run_experiment runs exactly 1 iteration if updates is empty."""
    config = ExperimentConfig(
        name="test_exp",
        base_working_directory=Path(),
        forward_model_steps=[],
        queue_config=QueueConfig(backend="local"),
        parameter_matrix=ParameterMatrix(values={"p1": {0: 1.0}}),
        observations=[],
        updates=[],
    )

    with (
        patch(
            "gert.experiment_runner.experiment_orchestrator.JobSubmitter",
            return_value=mock_job_submitter,
        ),
        patch(
            "gert.experiment_runner.experiment_orchestrator.RealizationWorkdirManager",
            return_value=mock_workdir_manager,
        ),
        patch(
            "gert.experiment_runner.experiment_orchestrator.StorageAPI",
            return_value=mock_storage,
        ),
    ):
        orchestrator = ExperimentOrchestrator(config=config, experiment_id="test-exp")

    callback: Any = None

    def side_effect_submit(
        execution_steps: list[str],
        directory: Path,
        status_callback: Any,
    ) -> str:
        nonlocal callback
        callback = status_callback
        return "job_1"

    mock_job_submitter.submit.side_effect = side_effect_submit

    task = asyncio.create_task(orchestrator.run_experiment())
    while callback is None:
        if task.done():
            await task
            pytest.fail("Task finished but callback was never set.")
        await asyncio.sleep(0.01)

    callback(MagicMock(spec=psij.Job), psij.JobStatus(psij.JobState.COMPLETED))
    await task

    assert mock_job_submitter.submit.call_count == 1
    assert 1 not in orchestrator._active_jobs
