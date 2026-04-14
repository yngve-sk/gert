"""Tests for Orchestrator completion fallbacks."""

import asyncio
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import psij
import pytest

from gert.experiment_runner.experiment_orchestrator import ExperimentOrchestrator
from gert.experiments.models import (
    ExecutableForwardModelStep,
    ExperimentConfig,
    ParameterMatrix,
    QueueConfig,
)


@pytest.fixture
def mock_storage() -> Generator[MagicMock]:
    with patch("gert.experiment_runner.experiment_orchestrator.StorageAPI") as mock:
        yield mock.return_value


@pytest.fixture
def base_config(tmp_path: Path) -> ExperimentConfig:
    # Minimal config for a single iteration, single realization
    return ExperimentConfig(
        name="test_experiment",
        base_working_directory=tmp_path,
        forward_model_steps=[
            ExecutableForwardModelStep(name="step1", executable="echo", args=["hello"]),
        ],
        queue_config=QueueConfig(backend="local"),
        parameter_matrix=ParameterMatrix(
            values={"p1": {0: 1.0, 1: 2.0}},
        ),
        observations=[],
    )


@pytest.mark.asyncio
async def test_psij_fallback_completion(
    base_config: ExperimentConfig,
    mock_storage: MagicMock,
    tmp_path: Path,
) -> None:
    """
    Verify that if the HTTP curl never arrives, the Orchestrator successfully
    completes the iteration by relying on the PSI/J COMPLETED daemon signal.
    """
    orchestrator = ExperimentOrchestrator(
        config=base_config,
        experiment_id="test-exp",
        api_url="http://localhost:8000",
    )

    # 1. Setup mock behavior for PSI/J
    # We want to capture the status callback passed to job_submitter.submit
    captured_callbacks = {}

    def mock_submit(*args: Any, **kwargs: Any) -> str:
        real_id = kwargs.get("realization_id")
        captured_callbacks[real_id] = kwargs.get("status_callback")
        return f"mock-job-{real_id}"

    with patch.object(orchestrator._job_submitter, "submit", side_effect=mock_submit):
        # Start iteration
        orchestrator.run_iteration(0, base_config.parameter_matrix)

        # Ensure we captured callbacks for all realizations
        assert len(captured_callbacks) == 2

        # 2. Simulate realization 0 completion via PSI/J daemon ONLY
        # We DO NOT call record_realization_complete(step_name="step1") which simulates the curl
        mock_job = MagicMock(spec=psij.Job)
        mock_status = MagicMock(spec=psij.JobStatus)
        mock_status.final = True
        mock_status.state = psij.JobState.COMPLETED

        # Trigger the daemon callback for realization 0
        if captured_callbacks[0]:
            captured_callbacks[0](mock_job, mock_status)

        # 3. Simulate realization 1 completion via PSI/J daemon ONLY
        if captured_callbacks[1]:
            captured_callbacks[1](mock_job, mock_status)

        # 4. Verification
        # The iteration event for iteration 0 should eventually be set
        # because realization 0 was finished via fallback, and 1 was finished manually.
        await asyncio.wait_for(orchestrator._iteration_events[0].wait(), timeout=1.0)
        assert orchestrator._iteration_events[0].is_set()
        assert 0 in orchestrator._successful_realizations[0]
        assert 1 in orchestrator._successful_realizations[0]
