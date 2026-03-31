"""Tests for the ExperimentOrchestrator's macro iteration loop using real components."""

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from gert.experiment_runner.experiment_orchestrator import ExperimentOrchestrator
from gert.experiments.models import (
    ExperimentConfig,
    ParameterMatrix,
    QueueConfig,
    UpdateStep,
)
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
def real_config(tmp_path: Path) -> ExperimentConfig:
    return ExperimentConfig(
        name="test_exp",
        base_working_directory=tmp_path,
        forward_model_steps=[],  # No steps = simple exit
        queue_config=QueueConfig(backend="local"),
        parameter_matrix=ParameterMatrix(
            values={"p1": {0: 1.0}},  # 1 realization
        ),
        observations=[],
        updates=[
            UpdateStep(name="step1", algorithm="mock_algo"),
        ],
    )


@pytest.mark.asyncio
async def test_run_experiment_loop_flow(
    real_config: ExperimentConfig,
    tmp_path: Path,
) -> None:
    """Verify that run_experiment executes N+1 iterations and calls updates."""

    orchestrator = ExperimentOrchestrator(
        config=real_config,
        experiment_id="test-exp",
    )

    # Mock plugin discovery
    mock_algo = MockUpdateAlgorithm()

    # Mock submitter just to avoid real local execution (PSI/J overhead)
    # and to track submissions
    mock_submitter = MagicMock()
    mock_submitter.submit.return_value = "job_id"

    with (
        patch.object(orchestrator, "_job_submitter", mock_submitter),
        patch.object(orchestrator._plugins, "update_algorithms", [mock_algo]),
    ):
        task = asyncio.create_task(orchestrator.run_experiment())

        # Give it a moment to start and write parameters
        await asyncio.sleep(0.1)

        # Iteration 0
        assert mock_submitter.submit.call_count == 1
        # In iteration 0, realization 0 is running.

        # Manually "ingest" a response so perform_update finds data
        exec_id = orchestrator.execution_id
        iter0_path = tmp_path / "permanent_storage" / "test_exp" / exec_id / "iter-0"
        iter0_path.mkdir(parents=True, exist_ok=True)
        resp_path = iter0_path / "responses"
        resp_path.mkdir(exist_ok=True)
        # Create a dummy parquet file that StorageAPI.get_responses will find
        pl.DataFrame(
            {"realization": [0], "value": [10.0], "key": ["FOPR"]},
        ).write_parquet(
            resp_path / "data_dummy.parquet",
        )

        # Simulate SDK signal /complete
        await orchestrator.record_realization_complete(iteration=0, realization_id=0)

        # Give it a moment to advance to Iteration 1
        # It needs to consolidate, update, and submit new jobs
        # Wait until submit count increases
        for _ in range(100):
            if mock_submitter.submit.call_count == 2:
                break
            await asyncio.sleep(0.02)

        assert mock_submitter.submit.call_count == 2

        # In Iteration 1, do the same
        iter1_path = tmp_path / "permanent_storage" / "test_exp" / exec_id / "iter-1"
        iter1_path.mkdir(parents=True, exist_ok=True)
        resp1_path = iter1_path / "responses"
        resp1_path.mkdir(exist_ok=True)
        pl.DataFrame(
            {"realization": [0], "value": [11.0], "key": ["FOPR"]},
        ).write_parquet(
            resp1_path / "data_dummy.parquet",
        )

        # Iteration 1 completion
        await orchestrator.record_realization_complete(iteration=1, realization_id=0)

        # The loop should now finish (0 updates left)
        await asyncio.wait_for(task, timeout=2.0)

    assert mock_submitter.submit.call_count == 2
    # Check that parameters were written for iters 0 and 1
    # Storage structure: storage_base / exp_name / exec_id / iter-N / parameters.parquet
    exec_id = orchestrator.execution_id
    storage_path = tmp_path / "permanent_storage" / "test_exp" / exec_id
    assert (storage_path / "iter-0" / "parameters.parquet").exists()
    assert (storage_path / "iter-1" / "parameters.parquet").exists()


@pytest.mark.asyncio
async def test_run_experiment_no_updates(
    real_config: ExperimentConfig,
    tmp_path: Path,
) -> None:
    """Verify that run_experiment runs exactly 1 iteration if updates is empty."""
    real_config.updates = []
    orchestrator = ExperimentOrchestrator(
        config=real_config,
        experiment_id="test-exp",
    )

    mock_submitter = MagicMock()
    mock_submitter.submit.return_value = "job_id"

    with patch.object(orchestrator, "_job_submitter", mock_submitter):
        task = asyncio.create_task(orchestrator.run_experiment())
        await asyncio.sleep(0.1)

        assert mock_submitter.submit.call_count == 1
        await orchestrator.record_realization_complete(iteration=0, realization_id=0)

        await asyncio.wait_for(task, timeout=2.0)

    assert mock_submitter.submit.call_count == 1
