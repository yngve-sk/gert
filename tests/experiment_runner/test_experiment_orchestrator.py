"""Tests for the ExperimentOrchestrator."""

import asyncio
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from gert.experiment_runner.experiment_orchestrator import ExperimentOrchestrator
from gert.experiment_runner.job_submitter import JobSubmitter
from gert.experiment_runner.realization_workdir_manager import RealizationWorkdirManager
from gert.experiments.models import (
    ExecutableForwardModelStep,
    ExperimentConfig,
    ParameterMatrix,
    PluginForwardModelStep,
    QueueConfig,
)


async def _wait_for_condition(
    condition: Callable[[], bool],
    timeout: float = 2.0,
    interval: float = 0.01,
) -> bool:
    """Wait for a condition to become true with a timeout."""
    start_time = time.time()
    while time.time() - start_time < timeout:
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
def job_submitter() -> JobSubmitter:
    """Provide a real local JobSubmitter."""
    return JobSubmitter(queue_config={}, executor_type="local")


@pytest.fixture
def workdir_manager(tmp_workdir: Path) -> RealizationWorkdirManager:
    """Provide a real RealizationWorkdirManager."""
    return RealizationWorkdirManager(base_workdir=tmp_workdir)


@pytest.fixture
def orchestrator(
    job_submitter: JobSubmitter,
    workdir_manager: RealizationWorkdirManager,
) -> ExperimentOrchestrator:
    """Provide an ExperimentOrchestrator instance with real dependencies."""
    return ExperimentOrchestrator(
        job_submitter=job_submitter,
        workdir_manager=workdir_manager,
    )


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
        exp_id = orchestrator.start_experiment(config)

        assert isinstance(exp_id, str)
        assert len(exp_id) > 0
        assert orchestrator._config == config
        assert orchestrator._execution_id == exp_id
        assert orchestrator._current_parameters == config.parameter_matrix

    def test_run_iteration_requires_start_experiment(
        self,
        orchestrator: ExperimentOrchestrator,
    ) -> None:
        """run_iteration raises RuntimeError if experiment has not been started."""
        with pytest.raises(RuntimeError, match="Experiment not started"):
            orchestrator.run_iteration(0, ParameterMatrix())

    def test_run_realization_requires_start_experiment(
        self,
        orchestrator: ExperimentOrchestrator,
    ) -> None:
        """run_realization raises RuntimeError if experiment has not been started."""
        with pytest.raises(RuntimeError, match="Experiment not started"):
            orchestrator.run_realization(0, 0)

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
        orchestrator.start_experiment(config)
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
        orchestrator.start_experiment(config)
        with pytest.raises(ValueError, match="Realization number must be >= 0"):
            orchestrator.run_realization(-1, 0)

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
        orchestrator.start_experiment(config)
        with pytest.raises(ValueError, match="Iteration number must be >= 0"):
            orchestrator.run_realization(0, -1)

    async def test_run_iteration_determines_unique_realizations_and_executes(
        self,
        orchestrator: ExperimentOrchestrator,
        tmp_path: Path,
    ) -> None:
        """run_iteration properly extracts unique realization IDs and executes them."""

        config = ExperimentConfig(
            name="test_experiment",
            base_working_directory=Path(),
            forward_model_steps=[
                ExecutableForwardModelStep(
                    name="step1",
                    executable="echo",
                    args=["realization_executed", ">>", str(tmp_path / "summary.txt")],
                ),
            ],
            queue_config=QueueConfig(backend="local"),
            parameter_matrix=ParameterMatrix(),
            observations=[],
        )
        orchestrator.start_experiment(config)

        parameters = ParameterMatrix(
            values={
                "param1": {0: 1.0, 1: 2.0},
                "param2": {1: 3.0, 2: 4.0},
            },
        )

        orchestrator.run_iteration(5, parameters)

        summary_file = tmp_path / "summary.txt"

        def check_summary_lines() -> bool:
            if not summary_file.exists():
                return False
            content = summary_file.read_text().strip().split("\n")
            return len(content) == 3

        assert await _wait_for_condition(check_summary_lines)

    async def test_run_realization_executes_correctly_and_creates_workdir(
        self,
        orchestrator: ExperimentOrchestrator,
        tmp_workdir: Path,
        tmp_path: Path,
    ) -> None:
        """run_realization correctly creates a workdir and submits a real job."""
        output_file = tmp_path / "realization_output.txt"

        config = ExperimentConfig(
            name="test_experiment",
            base_working_directory=Path(),
            forward_model_steps=[
                ExecutableForwardModelStep(
                    name="step1",
                    executable="echo",
                    args=["hello", ">", str(output_file)],
                ),
            ],
            queue_config=QueueConfig(backend="local"),
            parameter_matrix=ParameterMatrix(),
            observations=[],
        )
        exp_id = orchestrator.start_experiment(config)

        orchestrator.run_realization(
            realization_id=42,
            iteration=3,
        )

        # Verify workdir creation
        expected_workdir = (
            tmp_workdir / config.name / exp_id / "iter-3" / "realization-42"
        )
        assert expected_workdir.exists()
        assert expected_workdir.is_dir()

        # Verify real execution output
        assert await _wait_for_condition(output_file.exists)
        assert output_file.read_text().strip() == "hello"

    async def test_run_realization_ignores_plugin_steps(
        self,
        orchestrator: ExperimentOrchestrator,
        tmp_path: Path,
    ) -> None:
        """run_realization correctly filters out plugin steps from CLI execution."""
        output_file = tmp_path / "plugin_filter_output.txt"

        config = ExperimentConfig(
            name="test_experiment",
            base_working_directory=Path(),
            forward_model_steps=[
                ExecutableForwardModelStep(
                    name="step1",
                    executable="echo",
                    args=["hello", ">", str(output_file)],
                ),
                PluginForwardModelStep(
                    name="plugin1",
                    uses="some_plugin",
                ),
            ],
            queue_config=QueueConfig(backend="local"),
            parameter_matrix=ParameterMatrix(),
            observations=[],
        )

        orchestrator.start_experiment(config)
        orchestrator.run_realization(
            realization_id=0,
            iteration=0,
        )

        assert await _wait_for_condition(output_file.exists)
        assert output_file.read_text().strip() == "hello"
