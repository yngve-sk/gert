"""Orchestrator for coordinating experiment execution lifecycle."""

import uuid

from gert.experiments.models import (
    ExecutableForwardModelStep,
    ExperimentConfig,
    ParameterMatrix,
)

from .job_submitter import JobSubmitter
from .realization_workdir_manager import RealizationWorkdirManager


class ExperimentOrchestrator:
    """Coordinates the experiment execution lifecycle.

    Manages the orchestration flow: workdir creation, parameter injection,
    and job submission based on the immutable ExperimentConfig.
    """

    def __init__(
        self,
        job_submitter: JobSubmitter,
        workdir_manager: RealizationWorkdirManager,
    ) -> None:
        """Initialize the orchestrator with required dependencies.

        Args:
            job_submitter: Interface for submitting jobs to the execution backend.
            workdir_manager: Manager for creating and managing execution workdirs.
        """
        self._job_submitter = job_submitter
        self._workdir_manager = workdir_manager
        self._config: ExperimentConfig | None = None
        self._experiment_id: str | None = None
        self._current_parameters: ParameterMatrix | None = None

    def start_experiment(self, config: ExperimentConfig) -> str:
        """Start a new experiment execution based on the config.

        Args:
            config: The immutable experiment configuration containing all
                   execution parameters and forward model definitions.

        Returns:
            The experiment ID for tracking execution status.
        """
        self._config = config
        self._experiment_id = uuid.uuid4().hex
        self._current_parameters = config.parameter_matrix
        return self._experiment_id

    def run_iteration(self, iteration: int, parameters: ParameterMatrix) -> None:
        """Execute forward model for an iteration.

        Args:
            iteration: The iteration number.
            parameters: Parameter matrix to use.

        Raises:
            RuntimeError: If the experiment has not been started.
            ValueError: If the iteration number is negative.
        """
        if self._config is None or self._experiment_id is None:
            msg = "Experiment not started. Call start_experiment first."
            raise RuntimeError(msg)

        if iteration < 0:
            msg = f"Iteration number must be >= 0, got: {iteration}"
            raise ValueError(msg)

        self._current_parameters = parameters

        # Determine unique realizations from the parameter matrix
        realizations: set[int] = set()
        if parameters.values:
            for payload in parameters.values.values():
                realizations.update(payload.keys())

        for realization_id in realizations:
            self.run_realization(realization_id, iteration)

    def run_realization(self, realization_id: int, iteration: int) -> None:
        """Execute forward model for a specific realization.

        Args:
            realization_id: The realization ID.
            iteration: The iteration number.

        Raises:
            RuntimeError: If the experiment has not been started.
            ValueError: If the realization_id or iteration number is negative.
        """
        if self._config is None or self._experiment_id is None:
            msg = "Experiment not started. Call start_experiment first."
            raise RuntimeError(msg)

        if realization_id < 0:
            msg = f"Realization number must be >= 0, got: {realization_id}"
            raise ValueError(msg)

        if iteration < 0:
            msg = f"Iteration number must be >= 0, got: {iteration}"
            raise ValueError(msg)

        _workdir = self._workdir_manager.create_workdir(
            experiment_id=self._experiment_id,
            iteration=iteration,
            realization=realization_id,
        )

        execution_steps = []
        for step in self._config.forward_model_steps:
            if isinstance(step, ExecutableForwardModelStep):
                cmd_parts = [step.executable]
                cmd_parts.extend(step.args)
                execution_steps.append(" ".join(cmd_parts))

        self._job_submitter.submit(execution_steps=execution_steps)
