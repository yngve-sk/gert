import asyncio
import json
import os
import uuid
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

import polars as pl
import psij

from gert.experiments.models import (
    ExecutableForwardModelStep,
    ExecutableHook,
    ExperimentConfig,
    ParameterMatrix,
)
from gert.plugins.plugins import GertRuntimePlugins
from gert.storage.api import StorageAPI
from gert.storage.consolidation import ConsolidationWorker

from .job_submitter import JobSubmitter
from .realization_workdir_manager import RealizationWorkdirManager


class ExperimentOrchestrator:
    """Coordinates the experiment execution lifecycle.

    Manages the macro iteration loop (N+1), workdir creation, parameter injection,
    and mathematical updates based on the immutable ExperimentConfig.
    """

    @staticmethod
    def validate_config(config: ExperimentConfig) -> None:
        """Verify that a config is valid for execution on this host.

        This performs context-specific validations like checking if
        executables exist and are runnable.

        Args:
            config: The experiment configuration to validate.
        """
        # Only validate for local backend to avoid false negatives on cluster
        if config.queue_config.backend != "local":
            return

        # Check Forward Model Steps
        for step in config.forward_model_steps:
            if isinstance(step, ExecutableForwardModelStep):
                ExperimentOrchestrator._check_executable(
                    config,
                    step.executable,
                    f"Step '{step.name}'",
                )

        # Check Lifecycle Hooks
        for hook in config.lifecycle_hooks:
            if isinstance(hook, ExecutableHook):
                ExperimentOrchestrator._check_executable(
                    config,
                    hook.executable,
                    f"Hook '{hook.name}'",
                )

    @staticmethod
    def _check_executable(
        config: ExperimentConfig,
        exe_path: str,
        context: str,
    ) -> None:
        """Helper to check a single executable path.

        Raises:
            ValueError: If the executable is not found or not executable.
        """
        p = Path(exe_path)
        if not p.is_absolute():
            p = (config.base_working_directory / p).resolve()

        if not p.exists():
            msg = f"{context} executable not found: {p}"
            raise ValueError(msg)
        if not p.is_file():
            msg = f"{context} path is not a file: {p}"
            raise ValueError(msg)
        if not os.access(p, os.X_OK):
            msg = f"{context} file is not executable: {p}"
            raise ValueError(msg)

    def __init__(
        self,
        config: ExperimentConfig,
        experiment_id: str,
        run_count: int = 1,
        monitoring_callback: Callable[[int, int, str, str | None], None] | None = None,
        api_url: str | None = None,
    ) -> None:
        """Initialize the orchestrator using an immutable config as the base truth.

        Args:
            config: The strictly immutable experiment configuration.
            experiment_id: The unique UUID for the experiment configuration.
            run_count: The sequential run count for this experiment (defaults to 1).
            monitoring_callback: Optional callback to notify about job status changes.
            api_url: Optional base URL for the GERT server API.
        """
        self._config = config
        self._experiment_id = experiment_id
        self._monitoring_callback = monitoring_callback
        self._api_url = api_url

        # Constructor Completeness: Generate execution ID immediately
        exp_uuid = uuid.uuid4().hex
        self._execution_id = f"run_{run_count}-{exp_uuid}"

        # Instantiate internal dependencies based directly on the base truth config
        self._job_submitter = JobSubmitter(
            queue_config=config.queue_config.model_dump(),
            executor_type=config.queue_config.backend,
        )
        self._workdir_manager = RealizationWorkdirManager(
            base_workdir=config.realization_workdirs_base,
        )
        self._storage_api = StorageAPI(base_storage_path=config.storage_base)

        self._plugins = GertRuntimePlugins()

        # Track active jobs per iteration: {iteration: {realization_id: job_id}}
        self._active_jobs: dict[int, dict[int, str]] = defaultdict(dict)
        # Track completed jobs: {iteration: set(realization_id)}
        self._completed_realizations: dict[int, set[int]] = defaultdict(set)
        # Completion event per iteration
        self._iteration_events: dict[int, asyncio.Event] = {}

    def _ensure_iteration_state(self, iteration: int) -> None:
        """Ensure state structures exist for a given iteration."""
        if iteration not in self._iteration_events:
            self._iteration_events[iteration] = asyncio.Event()
        # defaultdict handles _active_jobs and _completed_realizations

    @property
    def execution_id(self) -> str:
        """Get the universally unique execution ID for this orchestrator instance."""
        return self._execution_id

    async def run_experiment(self) -> None:
        """Execute the full macro iteration loop (N+1 iterations)."""
        num_updates = len(self._config.updates)

        # Iteration 0 uses prior from config
        current_parameters = self._config.parameter_matrix

        # Write initial parameters to storage for iteration 0
        if self._storage_api:
            self._storage_api.write_parameters(
                experiment_id=self._config.name,
                execution_id=self._execution_id,
                iteration=0,
                parameters=self._parameter_matrix_to_df(current_parameters),
            )

        # Track consolidation background tasks
        consolidation_tasks: set[asyncio.Task[Any]] = set()

        for i in range(num_updates + 1):
            # 0. Start the consolidation background worker for this iteration
            if self._storage_api:
                worker = ConsolidationWorker(self._config.storage_base)
                queue_path = (
                    self._config.storage_base
                    / self._config.name
                    / self._execution_id
                    / f"iter-{i}"
                    / "ingestion_queue.jsonl"
                )
                watch_task = asyncio.create_task(
                    worker.start_watching(
                        queue_path,
                        self._config.consolidation_interval,
                    ),
                )
                consolidation_tasks.add(watch_task)
                watch_task.add_done_callback(consolidation_tasks.discard)

            # 1. Run Forward Models for this iteration
            self.run_iteration(i, current_parameters)

            # 2. Wait for all realizations in this iteration to finish
            await self._wait_for_iteration(i)

            # 3. Flush storage and cancel the watching task for this iteration
            if self._storage_api:
                if watch_task in consolidation_tasks:
                    watch_task.cancel()
                self._storage_api.flush(
                    experiment_id=self._config.name,
                    execution_id=self._execution_id,
                    iteration=i,
                )

            # 4. Perform Update (if not the last iteration)
            if i < num_updates:
                # perform_update returns a Wide DataFrame
                updated_params_df = self.perform_update(i)

                # Write posterior parameters to storage for the NEXT iteration
                self._storage_api.write_parameters(
                    experiment_id=self._config.name,
                    execution_id=self._execution_id,
                    iteration=i + 1,
                    parameters=updated_params_df,
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

        self._ensure_iteration_state(iteration)

        # Initialize all known realizations as PENDING via the callback
        if self._monitoring_callback:
            for r_id in sorted(realizations):
                self._monitoring_callback(r_id, iteration, "PENDING", None)

        for r_id in sorted(realizations):
            job_id = self.evaluate_forward_model(r_id, iteration)
            self._active_jobs[iteration][r_id] = job_id

    def evaluate_forward_model(self, realization_id: int, iteration: int) -> str:
        """Submit the forward model for a single realization.

        Args:
            realization_id: The ID of the realization to run.
            iteration: The current iteration number.

        Returns:
            The job ID from the job submitter.

        Raises:
            ValueError: If the realization_id or iteration is negative.
        """
        if realization_id < 0:
            msg = f"Realization number must be >= 0, got: {realization_id}"
            raise ValueError(msg)

        if iteration < 0:
            msg = f"Iteration number must be >= 0, got: {iteration}"
            raise ValueError(msg)

        workdir = self._workdir_manager.create_workdir(
            experiment_id=self._config.name,
            execution_id=self._execution_id,
            iteration=iteration,
            realization=realization_id,
        )

        self._inject_parameters(workdir, realization_id)

        # Build commands from config steps
        execution_steps = self._prepare_execution_steps(iteration, realization_id)

        status_cb = self._create_status_callback(
            iteration,
            realization_id,
            workdir,
            execution_steps,
        )

        return self._job_submitter.submit(
            execution_steps=execution_steps,
            directory=workdir,
            status_callback=status_cb,
            monitoring_url=self._api_url,
            experiment_id=self._experiment_id,
            execution_id=self._execution_id,
            iteration=iteration,
            realization_id=realization_id,
        )

    def _prepare_execution_steps(
        self,
        iteration: int,
        realization_id: int,
    ) -> list[dict[str, str]]:
        """Prepare execution steps for a realization."""
        execution_steps = []
        for step in self._config.forward_model_steps:
            if isinstance(step, ExecutableForwardModelStep):
                # Resolve executable path relative to base_working_directory
                exe_path = Path(step.executable)
                if not exe_path.is_absolute():
                    exe_path = (
                        self._config.base_working_directory / exe_path
                    ).resolve()

                cmd_parts = [str(exe_path)]
                for arg in step.args:
                    replaced = arg.replace("{experiment_id}", self._experiment_id)
                    replaced = replaced.replace("{execution_id}", self._execution_id)
                    # Use literal string for the placeholder match
                    replaced = replaced.replace("{iteration}", str(iteration))  # noqa: RUF027
                    replaced = replaced.replace("{realization}", str(realization_id))
                    cmd_parts.append(replaced)
                execution_steps.append(
                    {"name": step.name, "command": " ".join(cmd_parts)},
                )
        return execution_steps

    def _create_status_callback(
        self,
        iteration: int,
        realization_id: int,
        workdir: Path,
        execution_steps: list[dict[str, str]],
    ) -> Callable[[psij.Job, psij.JobStatus], None]:
        """Create a status callback for a job."""

        def _status_cb(_job: psij.Job, status: psij.JobStatus) -> None:
            if status.final:
                # Move logs from workdir to permanent storage
                logs_transferred = False
                for step in execution_steps:
                    name = step["name"]
                    stdout_file = workdir / f"{name}.stdout"
                    stderr_file = workdir / f"{name}.stderr"

                    if stdout_file.exists():
                        self._storage_api.write_step_log(
                            self._config.name,
                            self._execution_id,
                            iteration,
                            realization_id,
                            name,
                            stdout_file.read_text(encoding="utf-8"),
                            "stdout",
                        )
                        logs_transferred = True
                    if stderr_file.exists():
                        self._storage_api.write_step_log(
                            self._config.name,
                            self._execution_id,
                            iteration,
                            realization_id,
                            name,
                            stderr_file.read_text(encoding="utf-8"),
                            "stderr",
                        )
                        logs_transferred = True

                # If it failed but no logs were found, capture PSI/J or shell errors
                if status.state == psij.JobState.FAILED and not logs_transferred:
                    msg = f"Job failed without producing logs. Status: {status.message}"
                    first_step = (
                        execution_steps[0]["name"] if execution_steps else "unknown"
                    )
                    self._storage_api.write_step_log(
                        self._config.name,
                        self._execution_id,
                        iteration,
                        realization_id,
                        first_step,
                        msg,
                        "stderr",
                    )

                self._completed_realizations[iteration].add(realization_id)
                if len(self._completed_realizations[iteration]) == len(
                    self._active_jobs[iteration],
                ):
                    self._iteration_events[iteration].set()
            if self._monitoring_callback:
                self._monitoring_callback(
                    realization_id,
                    iteration,
                    status.state.name,
                    None,
                )

        return _status_cb

    def _inject_parameters(self, workdir: Path, realization_id: int) -> None:
        """Inject parameters.json into the realization workdir."""
        params = {}
        for key, val_dict in self._config.parameter_matrix.values.items():
            if realization_id in val_dict:
                params[key] = val_dict[realization_id]

        with (workdir / "parameters.json").open("w", encoding="utf-8") as f:
            json.dump(params, f)

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
            ValueError: If the iteration index is out of bounds or algorithm not found.
        """
        # 1. Fetch data from storage
        # current_parameters (from storage for this iteration)
        current_params_df = self._storage_api.get_parameters(
            experiment_id=self._config.name,
            execution_id=self._execution_id,
            iteration=iteration,
        )

        # simulated_responses (from storage for this iteration)
        obs_df = self._observations_to_df()
        sim_resp_df = self._storage_api.get_responses(
            experiment_id=self._config.name,
            execution_id=self._execution_id,
            iteration=iteration,
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

    def _parameter_matrix_to_df(self, pm: ParameterMatrix) -> pl.DataFrame:
        """Convert ParameterMatrix to a Wide DataFrame.

        Args:
            pm: The ParameterMatrix to convert.

        Returns:
            A Polars DataFrame where rows are realizations.
        """
        # Collect all realization IDs
        realizations: set[int] = set()
        for val_dict in pm.values.values():
            realizations.update(val_dict.keys())

        if not realizations:
            return pl.DataFrame({"realization": []})

        rows = []
        for r_id in sorted(realizations):
            row: dict[str, Any] = {"realization": r_id}
            for key, val_dict in pm.values.items():
                if r_id in val_dict:
                    row[key] = val_dict[r_id]
            rows.append(row)

        return pl.DataFrame(rows)
