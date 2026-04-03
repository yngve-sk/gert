import asyncio
import functools
import json
import logging
import os
import time
import uuid
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
import psij

from gert.experiments.models import (
    ExecutableForwardModelStep,
    ExecutableHook,
    ExecutionState,
    ExperimentConfig,
    ParameterMatrix,
    UpdateMetadata,
)
from gert.plugins.plugins import GertRuntimePlugins
from gert.storage.api import StorageAPI
from gert.storage.consolidation import ConsolidationWorker

from .job_submitter import JobSubmitter
from .realization_workdir_manager import RealizationWorkdirManager

logger = logging.getLogger(__name__)


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
        resume_state: ExecutionState | None = None,
    ) -> None:
        """Initialize the orchestrator using an immutable config as the base truth."""
        self._config = config
        self._experiment_id = experiment_id
        self._monitoring_callback = monitoring_callback
        self._api_url = api_url

        if resume_state:
            self._execution_id = resume_state.execution_id
            self._current_iteration = resume_state.current_iteration
        else:
            exp_uuid = uuid.uuid4().hex
            self._execution_id = f"run_{run_count}-{exp_uuid}"
            self._current_iteration = 0

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
        # Track realization outcomes
        self._successful_realizations: dict[int, set[int]] = defaultdict(set)
        self._failed_realizations: dict[int, set[int]] = defaultdict(set)

        if resume_state:
            self._successful_realizations[self._current_iteration] = set(
                resume_state.completed_realizations,
            )
            self._failed_realizations[self._current_iteration] = set(
                resume_state.failed_realizations,
            )

        # Track individual step outcomes: {iteration: {realization_id: set(step_name)}}
        self._successful_steps: dict[int, dict[int, set[str]]] = defaultdict(
            lambda: defaultdict(set),
        )
        self._failed_steps: dict[int, dict[int, set[str]]] = defaultdict(
            lambda: defaultdict(set),
        )
        # Track expected number of realizations per iteration
        self._expected_realizations: dict[int, int] = {}
        # Completion event per iteration
        self._iteration_events: dict[int, asyncio.Event] = {}

        self._pause_requested = False
        self._force_pause = False
        self._pause_event = asyncio.Event()

    def pause(self, *, force: bool = False) -> None:
        """Pause the experiment execution.

        If force=True, cancel running jobs immediately.
        Otherwise, wait for running jobs to finish but don't start new ones.
        """
        self._pause_requested = True
        self._force_pause = force
        self._pause_event.set()

        if force:
            for job_id in self._active_jobs[self._current_iteration].values():
                self._job_submitter.cancel(job_id)

    @property
    def is_paused(self) -> bool:
        return self._pause_requested

    @property
    def is_force_paused(self) -> bool:
        return self._force_pause

    def _ensure_iteration_state(self, iteration: int) -> None:
        """Ensure state structures exist for a given iteration."""
        if iteration not in self._iteration_events:
            self._iteration_events[iteration] = asyncio.Event()
        if iteration not in self._expected_realizations:
            self._expected_realizations[iteration] = 0
        # defaultdict handles other tracking structures

    @property
    def execution_id(self) -> str:
        """Get the universally unique execution ID for this orchestrator instance."""
        return self._execution_id

    async def record_realization_complete(
        self,
        iteration: int,
        realization_id: int,
        step_name: str | None = None,
    ) -> None:
        """Record that a realization or a specific step has completed successfully."""
        # If it already failed (e.g. via PSI/J supervisor), don't mark it successful
        if realization_id in self._failed_realizations[iteration]:
            return

        if step_name:
            logger.debug(
                f"Step '{step_name}' completed for realization {realization_id} "
                f"(iteration {iteration})",
            )
            self._successful_steps[iteration][realization_id].add(step_name)
            if self._monitoring_callback:
                try:
                    self._monitoring_callback(
                        realization_id,
                        iteration,
                        "COMPLETED",
                        step_name,
                    )
                except Exception as e:
                    logger.error(f"Monitoring callback failed: {e}")

        # A realization is complete only if ALL expected steps are successful
        expected_steps = {s.name for s in self._config.forward_model_steps}
        if (
            expected_steps.issubset(self._successful_steps[iteration][realization_id])
            and realization_id not in self._successful_realizations[iteration]
        ):
            msg = (
                f"Realization {realization_id} fully completed (iteration {iteration})"
            )
            logger.info(msg)
            self._successful_realizations[iteration].add(realization_id)
            if self._monitoring_callback:
                try:
                    self._monitoring_callback(realization_id, iteration, "COMPLETED", None)
                except Exception as e:
                    logger.error(f"Monitoring callback failed: {e}")

        await self._check_iteration_complete(iteration)

    async def record_realization_fail(
        self,
        iteration: int,
        realization_id: int,
        step_name: str | None = None,
    ) -> None:
        """Record that a realization or a specific step has failed."""
        if step_name:
            logger.error(
                f"Step '{step_name}' failed for realization {realization_id} "
                f"(iteration {iteration})",
            )
            self._failed_steps[iteration][realization_id].add(step_name)
            if self._monitoring_callback:
                try:
                    self._monitoring_callback(
                        realization_id,
                        iteration,
                        "FAILED",
                        step_name,
                    )
                except Exception as e:
                    logger.error(f"Monitoring callback failed: {e}")

        # ANY step failure fails the whole realization
        if realization_id not in self._failed_realizations[iteration]:
            self._failed_realizations[iteration].add(realization_id)
            # Ensure it is removed from successful if it was previously there
            self._successful_realizations[iteration].discard(realization_id)

            if self._monitoring_callback:
                try:
                    self._monitoring_callback(realization_id, iteration, "FAILED", None)
                except Exception as e:
                    logger.error(f"Monitoring callback failed: {e}")

        await self._check_iteration_complete(iteration)

    async def _check_iteration_complete(self, iteration: int) -> None:
        """Check if the iteration is finished (all done or any failed)."""
        num_accounted = len(self._successful_realizations[iteration]) + len(
            self._failed_realizations[iteration],
        )
        all_done = num_accounted == self._expected_realizations[iteration]
        any_failed = len(self._failed_realizations[iteration]) > 0

        if all_done or any_failed:
            # Yield control briefly to ensure monitoring/polling has a chance
            # to see the final statuses before the orchestrator unblocks
            # and potentially moves to the next iteration.
            await asyncio.sleep(0.1)
            self._iteration_events[iteration].set()

    async def run_experiment(self) -> None:  # noqa: C901
        """Execute the full macro iteration loop (N+1 iterations)."""
        num_updates = len(self._config.updates)

        # Iteration 0 uses prior from config
        current_parameters = self._config.parameter_matrix

        self._current_iteration = getattr(self, "_current_iteration", 0)

        # If resuming from > 0, we must load parameters from storage for that iteration
        if self._current_iteration > 0 and self._storage_api:
            # We don't overwrite Iteration 0's priors, we assume they are safe.
            # Instead we load the current iteration's parameters that were written
            # at the end of the previous iteration.
            param_df = self._storage_api.get_parameters(
                self._config.name,
                self._execution_id,
                self._current_iteration,
            )
            current_parameters = current_parameters.replace_values_from_df(param_df)
        elif self._current_iteration == 0:
            if self._storage_api:
                self._storage_api.write_parameters(
                    experiment_id=self._config.name,
                    execution_id=self._execution_id,
                    iteration=0,
                    parameters=current_parameters.to_df(
                        self._config.base_working_directory,
                    ),
                )

        consolidation_tasks: set[asyncio.Task[Any]] = set()

        for i in range(self._current_iteration, num_updates + 1):
            if self._pause_requested:
                break

            self._current_iteration = i
            logger.info(f"Starting iteration {i}/{num_updates}")
            # 0. Start the consolidation background worker for this iteration
            if self._storage_api:
                ensemble_path = (
                    self._config.storage_base
                    / self._config.name
                    / self._execution_id
                    / f"iter-{i}"
                )
                logger.info(f"Starting consolidation watcher for {ensemble_path}")
                worker = ConsolidationWorker.get_instance(ensemble_path)
                watch_task = asyncio.create_task(
                    worker.start_watching(
                        self._config.consolidation_interval,
                    ),
                )
                consolidation_tasks.add(watch_task)
                watch_task.add_done_callback(consolidation_tasks.discard)

            # 1. Run Forward Models for this iteration
            logger.info(f"Submitting forward models for iteration {i}")
            self.run_iteration(
                i,
                current_parameters,
            )
            
            # 2. Wait for all realizations in this iteration to finish
            logger.info(f"Waiting for iteration {i} realizations to complete...")
            await self._wait_for_iteration(i)
            logger.info(f"All realizations for iteration {i} completed.")

            if self._pause_requested:
                break

            # 3. Flush storage and cancel the watching task for this iteration
            if self._storage_api:
                logger.info(f"Flushing storage for iteration {i}")
                if watch_task in consolidation_tasks:
                    watch_task.cancel()
                await self._storage_api.flush(
                    experiment_id=self._config.name,
                    execution_id=self._execution_id,
                    iteration=i,
                )

            # 4. Perform Update (if not the last iteration)
            if i < num_updates:
                update_step = self._config.updates[i]
                start_ts = time.time()
                metadata = UpdateMetadata(
                    algorithm_name=update_step.algorithm,
                    status="RUNNING",
                    configuration=update_step.arguments,
                    start_time=datetime.now(tz=UTC).isoformat(),
                )

                if self._storage_api:
                    self._storage_api.write_update_metadata(
                        self._config.name,
                        self._execution_id,
                        i + 1,
                        metadata,
                    )

                try:
                    # Fetch dependencies early for metrics
                    prior_df = self._storage_api.get_parameters(
                        self._config.name,
                        self._execution_id,
                        i,
                    )

                    summary_data = self._storage_api.get_observation_summary(
                        self._config.name,
                        self._execution_id,
                        i,
                    )
                    misfit = (
                        summary_data.average_normalized_misfit if summary_data else 0.0
                    )
                    prior_var = self._calculate_variance(prior_df)

                    # perform_update returns a Wide DataFrame
                    updated_params_df = await self.perform_update(i)

                    posterior_var = self._calculate_variance(updated_params_df)

                    metadata.metrics = {
                        "misfit_bias": misfit,
                        "prior_variance": prior_var,
                        "posterior_variance": posterior_var,
                    }
                    metadata.status = "COMPLETED"

                except Exception as e:
                    logger.exception(f"Failed to perform update at iteration {i}")
                    metadata.status = "FAILED"
                    metadata.error = str(e)
                    if self._storage_api:
                        metadata.end_time = datetime.now(tz=UTC).isoformat()
                        metadata.duration_seconds = time.time() - start_ts
                        self._storage_api.write_update_metadata(
                            self._config.name,
                            self._execution_id,
                            i + 1,
                            metadata,
                        )
                    raise
                finally:
                    if self._storage_api and metadata.status == "COMPLETED":
                        metadata.end_time = datetime.now(tz=UTC).isoformat()
                        metadata.duration_seconds = time.time() - start_ts
                        self._storage_api.write_update_metadata(
                            self._config.name,
                            self._execution_id,
                            i + 1,
                            metadata,
                        )

                # Write posterior parameters to storage for the NEXT iteration
                self._storage_api.write_parameters(
                    experiment_id=self._config.name,
                    execution_id=self._execution_id,
                    iteration=i + 1,
                    parameters=updated_params_df,
                )

                # Prepare for next iteration's injection
                current_parameters = current_parameters.replace_values_from_df(
                    updated_params_df,
                )
            else:
                # Final posterior evaluation complete
                break

    def run_iteration(self, iteration: int, parameters: ParameterMatrix) -> None:
        """Execute forward model for all realizations in an iteration.

        Raises:
            ValueError: If the iteration number is negative.
        """
        if iteration < 0:
            msg = f"Iteration number must be >= 0, got: {iteration}"
            raise ValueError(msg)

        # Determine realizations from the parameter matrix
        realizations: set[int] = parameters.get_realizations(
            self._config.base_working_directory,
        )

        self._ensure_iteration_state(iteration)
        self._expected_realizations[iteration] = len(realizations)

        skip_realizations = (
            self._successful_realizations[iteration]
            | self._failed_realizations[iteration]
        )

        # Initialize all known realizations as PENDING via the callback
        if self._monitoring_callback:
            for r_id in sorted(realizations):
                if r_id not in skip_realizations:
                    try:
                        self._monitoring_callback(r_id, iteration, "PENDING", None)
                    except Exception as e:
                        logger.error(f"Monitoring callback failed: {e}")

        for r_id in sorted(realizations):
            if r_id in skip_realizations:
                continue
            if self._pause_requested:
                break
            job_id = self.evaluate_forward_model(r_id, iteration, parameters)
            self._active_jobs[iteration][r_id] = job_id

    def evaluate_forward_model(
        self,
        realization_id: int,
        iteration: int,
        parameters: ParameterMatrix,
    ) -> str:
        """Submit the forward model for a single realization.

        Args:
            realization_id: The ID of the realization to run.
            iteration: The current iteration number.
            parameters: The parameter matrix for this iteration.

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

        self._inject_parameters(workdir, realization_id, parameters)

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
        loop = asyncio.get_running_loop()

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

                # Track outcome from scheduler (primary role: catch failures)
                if status.state in {
                    psij.JobState.FAILED,
                    psij.JobState.CANCELED,
                }:
                    err_msg = getattr(status, 'message', None) or getattr(status, 'exception', 'No message')
                    logger.error(
                        f"PSI/J reported {status.state.name} for realization {realization_id}: "
                        f"{err_msg}"
                    )
                    asyncio.run_coroutine_threadsafe(
                        self.record_realization_fail(iteration, realization_id),
                        loop,
                    )  # Note: psij.JobState.COMPLETED is intentionally ignored here.
                # We wait for the SDK to call the /complete HTTP endpoint
                # to guarantee that all data ingestion is finished.

            if self._monitoring_callback:
                try:
                    loop.call_soon_threadsafe(
                        self._monitoring_callback,
                        realization_id,
                        iteration,
                        status.state.name,
                        None,
                    )
                except Exception as e:
                    logger.error(f"Monitoring callback threadsafe failed: {e}")

        return _status_cb

    def _inject_parameters(  # noqa: C901
        self,
        workdir: Path,
        realization_id: int,
        parameters: ParameterMatrix,
    ) -> None:
        """Inject parameters.json and field datasets into the realization workdir."""
        # 1. Inject scalar values into parameters.json
        params = {}
        for key, val_dict in parameters.values.items():
            if realization_id in val_dict:
                params[key] = val_dict[realization_id]

        with (workdir / "parameters.json").open("w", encoding="utf-8") as f:
            json.dump(params, f)

        # 2. Inject field datasets (ParameterDataset)
        for i, dataset in enumerate(parameters.datasets):
            source_path = Path(dataset.reference.path)
            if not source_path.is_absolute():
                source_path = (
                    self._config.base_working_directory / source_path
                ).resolve()

            if not source_path.exists():
                continue

            # Load the prior base dataset
            df = pl.read_parquet(source_path)

            # Filter for this specific realization
            if "realization" in df.columns:
                real_df = df.filter(pl.col("realization") == realization_id)
            else:
                # If no realization column, assume the file is for one realization.
                # Possible in partitioned schemes.
                real_df = df

            # Sort indices to match models.py `_merge_datasets` alignment
            if dataset.index_columns:
                real_df = real_df.sort(dataset.index_columns)

            # If the matrix contains updated values, overwrite them here
            if parameters.dataframe is not None:
                row_df = parameters.dataframe.filter(
                    pl.col("realization") == realization_id,
                )
                if len(row_df) > 0:
                    for param in dataset.parameters:
                        if param in row_df.columns:
                            # Extract the aggregated array/list
                            updated_vals = row_df[param].to_list()[0]
                            # Overwrite the physical parameter
                            real_df = real_df.with_columns(
                                pl.Series(name=param, values=updated_vals),
                            )

            # Determine target filename
            target_name = f"field_data_{i}.parquet"
            real_df.write_parquet(workdir / target_name)

    async def _wait_for_iteration(self, iteration: int) -> None:
        """Wait until all realizations in the iteration are final or paused.

        Raises:
            ValueError: If the iteration finishes early or has failures.
        """
        if self._expected_realizations.get(iteration, 0) == 0:
            return

        # Replace hardcoded timeout with indefinitely waiting for completion or pause
        tasks = [
            asyncio.create_task(self._iteration_events[iteration].wait()),
            asyncio.create_task(self._pause_event.wait()),
        ]

        _done, pending = await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()

        if self._force_pause:
            return

        # If graceful pause, wait for remaining to finish
        if self._pause_event.is_set() and not self._force_pause:
            await self._iteration_events[iteration].wait()

        # If not forcefully paused, check if there were failures
        if not self._force_pause:
            num_success = len(self._successful_realizations[iteration])
            num_failed = len(self._failed_realizations[iteration])
            num_total = self._expected_realizations.get(iteration, 0)

            if num_success + num_failed < num_total:
                msg = (
                    f"Iteration {iteration} finished early. "
                    f"{num_success}/{num_total} succeeded, {num_failed} failed."
                )
                raise ValueError(msg)

            if num_failed > 0:
                msg = (
                    f"Iteration {iteration} failed: "
                    f"{num_failed}/{num_total} realizations failed."
                )
                raise ValueError(msg)

    async def perform_update(self, iteration: int) -> pl.DataFrame:
        """Invoke the math plugin for the given iteration.

        Args:
            iteration: The iteration number whose results are being updated.

        Returns:
            The newly calculated parameter matrix as a Wide DataFrame.

        Raises:
            ValueError: If the iteration index is out of bounds or algorithm not found.
            FileNotFoundError: If responses are not found for the iteration.
        """
        # 0. Ensure data is consolidated before fetching
        logger.info(f"Performing mathematical update for iteration {iteration}")
        await self._storage_api.consolidate(self._config.name, self._execution_id)
        # Force flush the current iteration specifically to ensure everything is drained
        await self._storage_api.flush(
            self._config.name,
            self._execution_id,
            iteration,
        )

        # 1. Fetch data from storage
        # current_parameters (from storage for this iteration)
        current_params_df = self._storage_api.get_parameters(
            experiment_id=self._config.name,
            execution_id=self._execution_id,
            iteration=iteration,
        )

        # simulated_responses (from storage for this iteration)
        obs_df = self._observations_to_df()
        try:
            sim_resp_df = self._storage_api.get_responses(
                experiment_id=self._config.name,
                execution_id=self._execution_id,
                iteration=iteration,
            )
        except FileNotFoundError:
            logger.exception(f"Responses not found for iteration {iteration}!")
            # Check if there is anything in the ingestion_queue.jsonl
            ensemble_path = (
                self._config.storage_base
                / self._config.name
                / self._execution_id
                / f"iter-{iteration}"
            )
            queue_file = ensemble_path / "ingestion_queue.jsonl"
            if queue_file.exists():
                msg = (
                    f"Ingestion queue exists but responses don't! "
                    f"Size: {queue_file.stat().st_size}"
                )
                logger.exception(msg)
            else:
                logger.exception(f"Ingestion queue does not exist at {queue_file}!")
            raise

        if len(sim_resp_df) == 0:
            msg = (
                f"No responses found for iteration {iteration}. Update cannot proceed."
            )
            logger.error(msg)
            raise ValueError(msg)

        logger.info(f"Retrieved {len(sim_resp_df)} responses for iteration {iteration}")

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

        func = functools.partial(
            algo.perform_update,
            current_parameters=current_params_df,
            simulated_responses=sim_resp_df,
            observations=obs_df,
            updatable_parameter_keys=keys,
            algorithm_arguments=update_step.arguments,
        )

        return await asyncio.get_running_loop().run_in_executor(None, func)

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

    def _calculate_variance(self, df: pl.DataFrame) -> float:
        """Calculate the average variance of the parameter matrix."""
        try:
            numeric_df = df.select(
                pl.col(pl.Float64, pl.Float32, pl.Int64, pl.Int32).exclude(
                    "realization",
                ),
            )
            if len(numeric_df.columns) == 0:
                return 0.0

            variances = numeric_df.var()
            mean_var = variances.mean_horizontal()
            return (
                float(mean_var[0])
                if len(mean_var) > 0 and mean_var[0] is not None
                else 0.0
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Could not calculate variance: {e}")
            return 0.0
