"""Orchestrator for coordinating experiment execution lifecycle."""

import uuid
from collections.abc import Callable

import psij

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
        monitoring_callback: Callable[[int, int, str], None] | None = None,
    ) -> None:
        """Initialize the orchestrator with required dependencies.

        Args:
            job_submitter: Interface for submitting jobs to the execution backend.
            workdir_manager: Manager for creating and managing execution workdirs.
            monitoring_callback: Optional callback to notify about job status changes.
        """
        self._job_submitter = job_submitter
        self._workdir_manager = workdir_manager
        self._monitoring_callback = monitoring_callback
        self._config: ExperimentConfig | None = None
        self._experiment_id: str | None = None
        self._current_parameters: ParameterMatrix | None = None

    def start_experiment(
        self,
        config: ExperimentConfig,
    ) -> str:
        """Start a new experiment execution based on the config.

        Args:
            config: The immutable experiment configuration containing all
                   execution parameters and forward model definitions.

        Returns:
            The experiment ID for tracking execution status.
        """
        self._config = config
        exp_uuid = uuid.uuid4().hex
        self._experiment_id = f"{config.name}-{exp_uuid}"
        self._current_parameters = config.parameter_matrix
        return self._experiment_id

    def run_iteration(self, iteration: int, parameters: ParameterMatrix) -> str:
        """Execute forward model for an iteration.

        Args:
            iteration: The iteration number.
            parameters: Parameter matrix to use.

        Returns:
            The ensemble ID for this iteration.

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

        # Generate a stable ensemble_id for this iteration
        ensemble_uuid = uuid.uuid4().hex
        ensemble_id = f"run_{iteration}-{ensemble_uuid}"

        # Determine unique realizations from the parameter matrix
        realizations: set[int] = set()
        if parameters.values:
            for payload in parameters.values.values():
                realizations.update(payload.keys())

        for realization_id in realizations:
            self.run_realization(realization_id, iteration, ensemble_id)

        return ensemble_id

    def run_realization(
        self,
        realization_id: int,
        iteration: int,
        ensemble_id: str,
    ) -> None:
        """Execute forward model for a specific realization.

        Args:
            realization_id: The realization ID.
            iteration: The iteration number.
            ensemble_id: The unique ID for this ensemble/run.

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

        workdir = self._workdir_manager.create_workdir(
            experiment_id=self._experiment_id,
            ensemble_id=ensemble_id,
            realization=realization_id,
        )

        execution_steps = []
        for step in self._config.forward_model_steps:
            if isinstance(step, ExecutableForwardModelStep):
                cmd_parts = [step.executable]
                for arg in step.args:
                    # Replace standard placeholders
                    replaced_arg = (
                        arg.replace("{experiment_id}", self._experiment_id)
                        .replace("{iteration}", str(iteration))  # noqa: RUF027
                        .replace("{ensemble_id}", ensemble_id)
                        .replace("{realization}", str(realization_id))
                    )
                    cmd_parts.append(replaced_arg)
                execution_steps.append(" ".join(cmd_parts))

        def _status_cb(_job: psij.Job, status: psij.JobStatus) -> None:
            if self._monitoring_callback:
                self._monitoring_callback(realization_id, iteration, status.state.name)

        self._job_submitter.submit(
            execution_steps=execution_steps,
            directory=workdir,
            status_callback=_status_cb,
        )
