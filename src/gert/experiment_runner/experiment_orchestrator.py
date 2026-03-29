import asyncio
import uuid
from collections.abc import Callable
from typing import Any

import polars as pl
import psij

from gert.experiments.models import (
    ExecutableForwardModelStep,
    ExperimentConfig,
    ParameterMatrix,
)
from gert.plugins.plugins import GertRuntimePlugins
from gert.storage.api import StorageAPI

from .job_submitter import JobSubmitter
from .realization_workdir_manager import RealizationWorkdirManager


class ExperimentOrchestrator:
    """Coordinates the experiment execution lifecycle.

    Manages the macro iteration loop (N+1), workdir creation, parameter injection,
    and mathematical updates based on the immutable ExperimentConfig.
    """

    def __init__(
        self,
        config: ExperimentConfig,
        monitoring_callback: Callable[[int, int, str], None] | None = None,
    ) -> None:
        """Initialize the orchestrator using an immutable config as the base truth.

        Args:
            config: The strictly immutable experiment configuration.
            monitoring_callback: Optional callback to notify about job status changes.
        """
        self._config = config
        self._monitoring_callback = monitoring_callback

        # Instantiate internal dependencies based directly on the base truth config
        self._job_submitter = JobSubmitter(
            queue_config=config.queue_config.model_dump(),
            executor_type=config.queue_config.backend,
        )
        self._workdir_manager = RealizationWorkdirManager(
            base_workdir=config.realization_workdirs_base,
        )
        self._storage_api = StorageAPI(base_storage_path=config.storage_base)

        self._execution_id: str | None = None
        self._plugins = GertRuntimePlugins()

        # Track active jobs per iteration: {iteration: {realization_id: job_id}}
        self._active_jobs: dict[int, dict[int, str]] = {}
        # Track completed jobs: {iteration: set(realization_id)}
        self._completed_realizations: dict[int, set[int]] = {}
        # Completion event per iteration
        self._iteration_events: dict[int, asyncio.Event] = {}

    def start_experiment(
        self,
        run_count: int = 1,
    ) -> str:
        """Start a new experiment execution.

        Args:
            run_count: The sequential run count for this experiment.

        Returns:
            The execution ID for tracking status.
        """
        exp_uuid = uuid.uuid4().hex
        self._execution_id = f"run_{run_count}-{exp_uuid}"
        return self._execution_id

    async def run_experiment(self) -> None:
        """Execute the full macro iteration loop (N+1 iterations)."""
        exec_id = self.start_experiment()
        num_updates = len(self._config.updates)

        # Iteration 0 uses prior from config
        current_parameters = self._config.parameter_matrix

        for i in range(num_updates + 1):
            # 1. Run Forward Models for this iteration
            self.run_iteration(i, current_parameters)

            # 2. Wait for all realizations in this iteration to finish
            await self._wait_for_iteration(i)

            # 3. Flush storage to ensure all responses are consolidated
            self._storage_api.flush(self._config.name, exec_id, i)

            # 4. Perform Update (if not the last iteration)
            if i < num_updates:
                # perform_update returns a Wide DataFrame
                updated_params_df = self.perform_update(i)

                # Write posterior parameters to storage for the NEXT iteration
                self._storage_api.write_parameters(
                    self._config.name,
                    exec_id,
                    i + 1,
                    updated_params_df,
                )

                # Prepare for next iteration's injection
                current_parameters = self._df_to_parameter_matrix(updated_params_df)
            else:
                # Final posterior evaluation complete
                break

    def run_iteration(self, iteration: int, parameters: ParameterMatrix) -> None:
        """Execute forward model for all realizations in an iteration.

        Args:
            iteration: The current iteration number.
            parameters: The parameter matrix to use for this iteration.

        Raises:
            ValueError: If the iteration number is negative.
        """

        if iteration < 0:
            msg = f"Iteration number must be >= 0, got: {iteration}"
            raise ValueError(msg)

        # Determine realizations from the parameter matrix
        realizations: set[int] = set()
        if parameters.values:
            for payload in parameters.values.values():
                realizations.update(payload.keys())

        self._active_jobs[iteration] = {}
        self._completed_realizations[iteration] = set()
        self._iteration_events[iteration] = asyncio.Event()

        for r_id in sorted(realizations):
            job_id = self.evaluate_forward_model(r_id, iteration)
            self._active_jobs[iteration][r_id] = job_id

    def evaluate_forward_model(self, realization_id: int, iteration: int) -> str:  # noqa: C901
        """Submit the forward model for a single realization.

        Args:
            realization_id: The ID of the realization to run.
            iteration: The current iteration number.

        Returns:
            The job ID from the job submitter.

        Raises:
            RuntimeError: If the experiment has not been started.
            ValueError: If the realization_id or iteration is negative.
        """
        if self._execution_id is None:
            msg = "Experiment not started."
            raise RuntimeError(msg)

        if realization_id < 0:
            msg = f"Realization number must be >= 0, got: {realization_id}"
            raise ValueError(msg)

        if iteration < 0:
            msg = f"Iteration number must be >= 0, got: {iteration}"
            raise ValueError(msg)

        workdir = self._workdir_manager.create_workdir(
            experiment_name=self._config.name,
            execution_id=self._execution_id,
            iteration=iteration,
            realization=realization_id,
        )

        # Build commands from config steps
        execution_steps = []
        for step in self._config.forward_model_steps:
            if isinstance(step, ExecutableForwardModelStep):
                cmd_parts = [step.executable]
                for arg in step.args:
                    replaced = (
                        arg.replace("{execution_id}", self._execution_id)
                        .replace("{iteration}", str(iteration))  # noqa: RUF027
                        .replace("{realization}", str(realization_id))
                    )
                    cmd_parts.append(replaced)
                execution_steps.append(" ".join(cmd_parts))

        def _status_cb(_job: psij.Job, status: psij.JobStatus) -> None:
            if status.final:
                self._completed_realizations[iteration].add(realization_id)
                if len(self._completed_realizations[iteration]) == len(
                    self._active_jobs[iteration],
                ):
                    self._iteration_events[iteration].set()
            if self._monitoring_callback:
                self._monitoring_callback(realization_id, iteration, status.state.name)

        return self._job_submitter.submit(
            execution_steps=execution_steps,
            directory=workdir,
            status_callback=_status_cb,
        )

    async def _wait_for_iteration(self, iteration: int) -> None:
        """Wait until all realizations in the iteration are final."""
        if len(self._active_jobs[iteration]) == 0:
            return
        await self._iteration_events[iteration].wait()

    def perform_update(self, iteration: int) -> pl.DataFrame:
        """Invoke the math plugin for the given iteration.

        Args:
            iteration: The iteration number whose results are being updated.

        Returns:
            The newly calculated parameter matrix as a Wide DataFrame.

        Raises:
            RuntimeError: If experiment is not started or storage is missing.
            ValueError: If the iteration index is out of bounds or algorithm not found.
        """
        if self._execution_id is None:
            msg = "Experiment not started."
            raise RuntimeError(msg)

        if not self._storage_api:
            msg = "Storage Query API required for updates."
            raise RuntimeError(msg)

        # 1. Fetch data from storage
        # current_parameters (from storage for this iteration)
        current_params_df = self._storage_api.get_parameters(
            self._config.name,
            self._execution_id,
            iteration,
        )

        # simulated_responses (from storage for this iteration)
        obs_df = self._observations_to_df()
        sim_resp_df = self._storage_api.get_responses(
            self._config.name,
            self._execution_id,
            iteration,
        )

        # 2. Find and execute plugin
        update_step = self._config.updates[iteration]
        algo = next(
            (
                a
                for a in self._plugins.update_algorithms
                if a.name == update_step.algorithm
            ),
            None,
        )

        if not algo:
            msg = f"Update algorithm '{update_step.algorithm}' not found."
            raise ValueError(msg)

        # updatable_keys
        keys = update_step.updatable_parameters or [
            k for k, v in self._config.parameter_matrix.metadata.items() if v.updatable
        ]

        return algo.perform_update(
            current_parameters=current_params_df,
            simulated_responses=sim_resp_df,
            observations=obs_df,
            updatable_parameter_keys=keys,
            algorithm_arguments=update_step.arguments,
        )

    def _observations_to_df(self) -> pl.DataFrame:
        """Convert observations to a Wide DataFrame."""
        data = []
        for obs in self._config.observations:
            row: dict[str, Any] = dict(obs.key)
            row["value"] = obs.value
            row["std_dev"] = obs.std_dev
            if obs.coordinates:
                row.update(obs.coordinates)
            data.append(row)
        return pl.DataFrame(data)

    def _df_to_parameter_matrix(self, df: pl.DataFrame) -> ParameterMatrix:
        """Convert a Wide DataFrame back to ParameterMatrix.

        Args:
            df: The Wide DataFrame to convert.

        Returns:
            A ParameterMatrix instance.


        """

        new_values: dict[str, dict[int, Any]] = {}
        for col in df.columns:
            if col == "realization":
                continue
            new_values[col] = dict(zip(df["realization"], df[col], strict=False))

        return ParameterMatrix(
            metadata=self._config.parameter_matrix.metadata,
            values=new_values,
            # Datasets are not explicitly handled in this simple conversion yet
            datasets=self._config.parameter_matrix.datasets,
        )
