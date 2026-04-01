"""Tests for the ExperimentOrchestrator."""

import asyncio
import time
from collections.abc import Callable
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


async def _wait_for_condition(
    condition: Callable[[], bool],
    timeout_seconds: float = 2.0,
    interval: float = 0.01,
) -> bool:
    """Wait for a condition to become true with a timeout."""
    start_time = time.time()
    while time.time() - start_time < timeout_seconds:
        if condition():
            return True
        await asyncio.sleep(interval)
    return False


@pytest.fixture
def tmp_workdir(tmp_path: Path) -> Path:
    """Provide a temporary base workdir."""
    workdir = tmp_path / "workdirs"
    workdir.mkdir()
    return workdir


@pytest.fixture
def base_config() -> ExperimentConfig:

    return ExperimentConfig(
        name="test_experiment",
        base_working_directory=Path(),
        forward_model_steps=[],
        queue_config=QueueConfig(backend="local"),
        parameter_matrix=ParameterMatrix(),
        observations=[],
    )


@pytest.fixture
def orchestrator(base_config: ExperimentConfig) -> ExperimentOrchestrator:
    """Provide an ExperimentOrchestrator instance with real dependencies."""
    return ExperimentOrchestrator(config=base_config, experiment_id="test-exp-id")


class TestExperimentOrchestrator:
    """Test suite for ExperimentOrchestrator using real behavior without mocks."""

    def test_start_experiment_initializes_state(
        self,
        orchestrator: ExperimentOrchestrator,
    ) -> None:
        """start_experiment correctly initializes the orchestrator state."""
        config = ExperimentConfig(
            name="test_experiment",
            base_working_directory=Path(),
            forward_model_steps=[],
            queue_config=QueueConfig(backend="local"),
            parameter_matrix=ParameterMatrix(),
            observations=[],
        )
        orchestrator._config = config
        exp_id = orchestrator.execution_id

        assert isinstance(exp_id, str)
        assert len(exp_id) > 0
        assert orchestrator._config == config
        assert orchestrator._execution_id == exp_id

    def test_run_iteration_rejects_negative_iteration(
        self,
        orchestrator: ExperimentOrchestrator,
    ) -> None:
        """run_iteration raises ValueError for negative iterations."""
        config = ExperimentConfig(
            name="test_experiment",
            base_working_directory=Path(),
            forward_model_steps=[],
            queue_config=QueueConfig(backend="local"),
            parameter_matrix=ParameterMatrix(),
            observations=[],
        )
        orchestrator = ExperimentOrchestrator(config=config, experiment_id="test-exp")
        with pytest.raises(ValueError, match="Iteration number must be >= 0"):
            orchestrator.run_iteration(-1, ParameterMatrix())

    def test_run_realization_rejects_negative_realization(
        self,
        orchestrator: ExperimentOrchestrator,
    ) -> None:
        """run_realization raises ValueError for negative realization IDs."""
        config = ExperimentConfig(
            name="test_experiment",
            base_working_directory=Path(),
            forward_model_steps=[],
            queue_config=QueueConfig(backend="local"),
            parameter_matrix=ParameterMatrix(),
            observations=[],
        )
        orchestrator = ExperimentOrchestrator(config=config, experiment_id="test-exp")
        with pytest.raises(ValueError, match="Realization number must be >= 0"):
            orchestrator.evaluate_forward_model(-1, 0, ParameterMatrix())

    def test_run_realization_rejects_negative_iteration(
        self,
        orchestrator: ExperimentOrchestrator,
    ) -> None:
        """run_realization raises ValueError for negative iterations."""
        config = ExperimentConfig(
            name="test_experiment",
            base_working_directory=Path(),
            forward_model_steps=[],
            queue_config=QueueConfig(backend="local"),
            parameter_matrix=ParameterMatrix(),
            observations=[],
        )
        orchestrator = ExperimentOrchestrator(config=config, experiment_id="test-exp")
        with pytest.raises(ValueError, match="Iteration number must be >= 0"):
            orchestrator.evaluate_forward_model(0, -1, ParameterMatrix())

    async def test_run_iteration_determines_unique_realizations_and_executes(
        self,
        orchestrator: ExperimentOrchestrator,
        tmp_path: Path,
    ) -> None:
        """run_iteration properly extracts unique realization IDs and executes them."""

        config = ExperimentConfig(
            name="test_experiment",
            base_working_directory=tmp_path,
            forward_model_steps=[
                ExecutableForwardModelStep(
                    name="step1",
                    executable="echo",
                    args=["realization_executed"],
                ),
            ],
            queue_config=QueueConfig(backend="local"),
            parameter_matrix=ParameterMatrix(),
            observations=[],
        )
        orchestrator = ExperimentOrchestrator(config=config, experiment_id="test-exp")

        # Mock submitter to write logs and call callback immediately
        def side_effect_submit(
            execution_steps: list[dict[str, str]],
            directory: Path,
            status_callback: Callable[[psij.Job, psij.JobStatus], None],
            **kwargs: Any,
        ) -> str:
            # Write expected output files to directory
            for step in execution_steps:
                (directory / f"{step['name']}.stdout").write_text(
                    "realization_executed",
                )

            # Trigger completion
            job = MagicMock(spec=psij.Job)
            status = psij.JobStatus(psij.JobState.COMPLETED)
            status_callback(job, status)
            return "job_id"

        with patch.object(
            orchestrator._job_submitter,
            "submit",
            side_effect=side_effect_submit,
        ):
            parameters = ParameterMatrix(
                values={
                    "param1": {0: 1.0, 1: 2.0},
                    "param2": {1: 3.0, 2: 4.0},
                },
            )

            orchestrator.run_iteration(0, parameters)

        # Verification using StorageAPI
        storage = orchestrator._storage_api
        exec_id = orchestrator.execution_id

        # Should have executed for realizations 0, 1, 2
        for r_id in [0, 1, 2]:
            log = storage.get_step_log(config.name, exec_id, 0, r_id, "step1", "stdout")
            assert "realization_executed" in log

    async def test_run_realization_executes_correctly_and_creates_workdir(
        self,
        tmp_workdir: Path,
        tmp_path: Path,
    ) -> None:
        """run_realization correctly creates a workdir and submits a real job."""
        config = ExperimentConfig(
            name="test_experiment",
            base_working_directory=tmp_path,
            realization_workdirs_base=tmp_workdir,
            forward_model_steps=[
                ExecutableForwardModelStep(
                    name="step1",
                    executable="echo",
                    args=["hello"],
                ),
            ],
            queue_config=QueueConfig(backend="local"),
            parameter_matrix=ParameterMatrix(),
            observations=[],
        )
        orchestrator = ExperimentOrchestrator(config=config, experiment_id="test-exp")
        exp_id = orchestrator.execution_id
        storage = orchestrator._storage_api

        # Mock submitter
        def side_effect_submit(
            execution_steps: list[dict[str, str]],
            directory: Path,
            status_callback: Callable[[psij.Job, psij.JobStatus], None],
            **kwargs: Any,
        ) -> str:
            # Write expected output files to directory
            for step in execution_steps:
                (directory / f"{step['name']}.stdout").write_text("hello")

            # Trigger completion
            job = MagicMock(spec=psij.Job)
            status = psij.JobStatus(psij.JobState.COMPLETED)
            status_callback(job, status)
            return "job_1"

        with patch.object(
            orchestrator._job_submitter,
            "submit",
            side_effect=side_effect_submit,
        ):
            orchestrator._ensure_iteration_state(3)
            orchestrator._expected_realizations[3] = 1
            orchestrator.evaluate_forward_model(
                realization_id=42,
                iteration=3,
                parameters=ParameterMatrix(),
            )

        # Verify workdir creation
        expected_workdir = (
            tmp_workdir / config.name / exp_id / "iter-3" / "realization-42"
        )
        assert expected_workdir.exists()
        assert expected_workdir.is_dir()

        # Verify log movement
        log = storage.get_step_log(config.name, exp_id, 3, 42, "step1", "stdout")
        assert log.strip() == "hello"
