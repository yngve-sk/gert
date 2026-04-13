import asyncio
from pathlib import Path
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
def mock_storage():
    with patch("gert.experiment_runner.experiment_orchestrator.StorageAPI") as mock:
        yield mock.return_value


@pytest.fixture
def base_config(tmp_path: Path) -> ExperimentConfig:
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
async def test_job_fails_after_curl_success(base_config, mock_storage, tmp_path):
    """
    Test edge case where HTTP CURL succeeds (COMPLETED), but the psij callback later
    erroneously reports FAILED or throws an error. FAILED should be ignored.
    """
    orchestrator = ExperimentOrchestrator(
        config=base_config,
        experiment_id="test-exp",
        api_url="http://localhost:8000",
    )

    captured_callbacks = {}

    def mock_submit(*args, **kwargs):
        real_id = kwargs.get("realization_id")
        captured_callbacks[real_id] = kwargs.get("status_callback")
        return f"mock-job-{real_id}"

    with patch.object(orchestrator._job_submitter, "submit", side_effect=mock_submit):
        orchestrator.run_iteration(0, base_config.parameter_matrix)

        # HTTP CURL completes the realization early
        await orchestrator.record_realization_complete(0, 0, "step1")

        # Ensure it is marked successful
        assert 0 in orchestrator._successful_realizations[0]

        # Now PSI/J daemon fails later
        mock_job = MagicMock(spec=psij.Job)
        mock_status = MagicMock(spec=psij.JobStatus)
        mock_status.final = True
        mock_status.state = psij.JobState.FAILED

        # Trigger the daemon callback
        captured_callbacks[0](mock_job, mock_status)

        # Yield loop
        await asyncio.sleep(0.01)

        # FAILED list must be empty because the realization was already completely successful
        assert 0 not in orchestrator._failed_realizations[0]


@pytest.mark.asyncio
async def test_psij_callback_exception_safety(base_config, mock_storage, tmp_path):
    """
    Verify that an exception inside the PSI/J daemon callback doesn't
    crash the thread, but is gracefully caught by the broad try-except block.
    """
    orchestrator = ExperimentOrchestrator(
        config=base_config,
        experiment_id="test-exp",
        api_url="http://localhost:8000",
    )

    captured_callbacks = {}

    def mock_submit(*args, **kwargs):
        real_id = kwargs.get("realization_id")
        captured_callbacks[real_id] = kwargs.get("status_callback")
        return f"mock-job-{real_id}"

    with patch.object(orchestrator._job_submitter, "submit", side_effect=mock_submit):
        orchestrator.run_iteration(0, base_config.parameter_matrix)

        mock_job = MagicMock(spec=psij.Job)
        mock_status = MagicMock()
        # Create a mock object that throws an Exception when .final is accessed
        type(mock_status).final = getattr(
            type(mock_status),
            "final",
            property(
                lambda self: (_ for _ in ()).throw(ValueError("Intentional crash")),
            ),
        )

        # If it's not wrapped in try-except, this line will throw the error and fail the test
        captured_callbacks[0](mock_job, mock_status)

        assert True, "Survived deliberate crash inside psij callback"
