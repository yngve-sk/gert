"""Query API for GERT storage."""

import json
import typing
from pathlib import Path
from typing import Any

import polars as pl

from gert.experiments.models import (
    ExecutionState,
    ExperimentConfig,
    ObservationDetail,
    ObservationSummary,
    UpdateMetadata,
)
from gert.storage.consolidation import ConsolidationWorker


class StorageAPI:
    """Provides methods to query consolidated experiment data."""

    def __init__(self, base_storage_path: Path) -> None:
        """Initialize the query API with a base storage path."""
        self._base_storage_path = base_storage_path

    async def flush(
        self,
        experiment_id: str,
        execution_id: str,
        iteration: int,
    ) -> bool:
        """Forces the Consolidator to drain the queue entirely before returning."""
        ensemble_path = (
            self._base_storage_path / experiment_id / execution_id / f"iter-{iteration}"
        )
        worker = ConsolidationWorker.get_instance(ensemble_path)

        if ensemble_path.exists():
            await worker.consolidate()
        return True

    def get_update_metadata(
        self,
        experiment_id: str,
        execution_id: str,
        iteration: int,
    ) -> UpdateMetadata:
        """Retrieve the metadata for a specific update step.

        Raises:
            FileNotFoundError: If the update metadata file does not exist.
        """
        meta_file = (
            self._base_storage_path
            / experiment_id
            / execution_id
            / f"iter-{iteration}"
            / "update_metadata.json"
        )
        if not meta_file.exists():
            msg = f"Update metadata for iteration {iteration} not found."
            raise FileNotFoundError(msg)
        return UpdateMetadata.model_validate_json(meta_file.read_text(encoding="utf-8"))

    def write_update_metadata(
        self,
        experiment_id: str,
        execution_id: str,
        iteration: int,
        metadata: UpdateMetadata,
    ) -> None:
        """Write metadata for an update step to the posterior iteration's directory."""
        iter_dir = (
            self._base_storage_path / experiment_id / execution_id / f"iter-{iteration}"
        )
        iter_dir.mkdir(parents=True, exist_ok=True)
        meta_file = iter_dir / "update_metadata.json"
        meta_file.write_text(metadata.model_dump_json(indent=2), encoding="utf-8")

    def get_observation_summary(  # noqa: C901
        self,
        experiment_id: str,
        execution_id: str,
        iteration: int,
    ) -> ObservationSummary | None:
        """Calculate and return observation summary statistics.

        Caches the result if the iteration is completed.
        """
        iter_dir = (
            self._base_storage_path / experiment_id / execution_id / f"iter-{iteration}"
        )
        summary_file = iter_dir / "observation_summary.json"

        if summary_file.exists():
            try:
                return ObservationSummary.model_validate_json(
                    summary_file.read_text(encoding="utf-8"),
                )
            except (json.JSONDecodeError, ValueError):
                pass

        try:
            config_file = self._base_storage_path / experiment_id / "config.json"
            if not config_file.exists():
                return None

            config = ExperimentConfig.model_validate_json(
                config_file.read_text(encoding="utf-8"),
            )

            data = []
            for obs in config.observations:
                row: dict[str, Any] = dict(obs.key)
                row["value_obs"] = obs.value
                row["std_dev"] = obs.std_dev
                if obs.coordinates:
                    row.update(obs.coordinates)
                data.append(row)
            obs_df = pl.DataFrame(data)

            try:
                sim_resp_df = self.get_responses(experiment_id, execution_id, iteration)
            except FileNotFoundError:
                return None

            if len(sim_resp_df) == 0:
                return None

            common_cols = [
                c
                for c in obs_df.columns
                if c in sim_resp_df.columns
                and c not in {"value", "value_obs", "std_dev"}
            ]
            if not common_cols:
                return None

            joined = sim_resp_df.join(obs_df, on=common_cols, how="inner")
            if len(joined) == 0:
                return None

            # Residuals and misfits
            # residual: The raw error (simulation - observation).
            # absolute_misfit: The absolute error in terms of std deviations.
            residual = joined["value"] - joined["value_obs"]
            normal_misfit = residual / joined["std_dev"]

            # Scale into [-1, 1] range while preserving 0 as a perfect match.
            # We do this by dividing by the maximum absolute error in the ensemble.
            max_abs_misfit = normal_misfit.abs().max()
            scaling_factor = max_abs_misfit if max_abs_misfit != 0.0 else 1.0

            normalized_misfit = normal_misfit / scaling_factor

            joined = joined.with_columns(
                residual.alias("residual"),
                residual.abs().alias("absolute_residual"),
                normal_misfit.alias("normal_misfit"),
                normal_misfit.abs().alias("absolute_misfit"),
                normalized_misfit.alias("normalized_misfit"),
            )

            # Aggregate totals across all observations
            mean_norm_misfit = joined["normalized_misfit"].mean()
            mean_abs_res = joined["absolute_residual"].mean()
            mean_abs_misfit = joined["absolute_misfit"].mean()

            avg_norm_misfit = (
                float(typing.cast("float", mean_norm_misfit))
                if isinstance(mean_norm_misfit, (int, float))
                else 0.0
            )
            avg_abs_res = (
                float(typing.cast("float", mean_abs_res))
                if isinstance(mean_abs_res, (int, float))
                else 0.0
            )
            avg_abs_misfit = (
                float(typing.cast("float", mean_abs_misfit))
                if isinstance(mean_abs_misfit, (int, float))
                else 0.0
            )

            # Details exposes various misfit metrics per observation, averaged
            details_df = joined.group_by(common_cols).agg(
                pl.col("absolute_residual").mean(),
                pl.col("normalized_misfit").mean(),
                pl.col("absolute_misfit").mean(),
            )

            # Convert to list of dicts with native Python types
            details = []
            for row in details_df.to_dicts():
                abs_res = float(row.get("absolute_residual", 0.0))
                norm_misfit = float(row.get("normalized_misfit", 0.0))
                abs_misfit = float(row.get("absolute_misfit", 0.0))

                key_dict = {
                    str(k): str(v)
                    for k, v in row.items()
                    if k
                    not in {"absolute_residual", "normalized_misfit", "absolute_misfit"}
                }
                response_val = key_dict.pop("response", None)

                details.append(
                    ObservationDetail(
                        response=response_val,
                        key=key_dict,
                        absolute_residual=abs_res,
                        normalized_misfit=norm_misfit,
                        absolute_misfit=abs_misfit,
                    ),
                )

            result = ObservationSummary(
                average_normalized_misfit=avg_norm_misfit,
                average_absolute_residual=avg_abs_res,
                average_absolute_misfit=avg_abs_misfit,
                details=details,
            )

            state_file = (
                self._base_storage_path
                / experiment_id
                / execution_id
                / "execution_state.json"
            )
            if state_file.exists():
                state = ExecutionState.model_validate_json(
                    state_file.read_text(encoding="utf-8"),
                )
                if state.current_iteration > iteration or state.status in {
                    "COMPLETED",
                    "FAILED",
                    "CANCELED",
                }:
                    iter_dir.mkdir(parents=True, exist_ok=True)
                    summary_file.write_text(
                        result.model_dump_json(indent=2),
                        encoding="utf-8",
                    )

        except Exception:  # noqa: BLE001
            return None
        else:
            return result

    def get_responses(
        self,
        experiment_id: str,
        execution_id: str,
        iteration: int,
    ) -> pl.DataFrame:
        """Retrieve all consolidated responses for an experiment and iteration.

        Reads the schema-partitioned response files without relying on a registry
        and vertically concatenates them into a massive Tidy (Long) DataFrame.

        Raises:
            FileNotFoundError: If the consolidated data doesn't exist.
        """
        iter_dir = (
            self._base_storage_path / experiment_id / execution_id / f"iter-{iteration}"
        )
        resp_dir = iter_dir / "responses"

        schema_files = list(resp_dir.glob("*.parquet"))
        if not schema_files:
            schema_files = list(iter_dir.glob("responses_*.parquet"))

        if not schema_files:
            legacy = iter_dir / "responses.parquet"
            if legacy.exists():
                return pl.read_parquet(legacy)
            msg = f"Consolidated data for experiment '{experiment_id}' not found."
            raise FileNotFoundError(msg)

        dfs = [pl.read_parquet(f) for f in schema_files]
        return pl.concat(dfs, how="diagonal")

    def get_parameters(
        self,
        experiment_id: str,
        execution_id: str,
        iteration: int,
    ) -> pl.DataFrame:
        """Retrieve the parameter matrix used for a specific iteration.

        Infers spatial fields by scanning parquet schemas, sorts them by their
        coordinate columns, and groups them into List columns.

        Raises:
            FileNotFoundError: If the parameters for the iteration are not found.
        """
        iter_dir = (
            self._base_storage_path / experiment_id / execution_id / f"iter-{iteration}"
        )
        param_dir = iter_dir / "parameters"

        schema_files = list(param_dir.glob("*.parquet"))
        if not schema_files:
            schema_files = list(iter_dir.glob("parameters_*.parquet"))

        dfs = []
        for filepath in schema_files:
            df = pl.read_parquet(filepath)

            if len(df) == df["realization"].n_unique():
                dfs.append(df)
            else:
                sort_cols = [c for c in df.columns if c != "realization"]
                df = df.sort(sort_cols)
                grouped = df.group_by("realization", maintain_order=True).agg(pl.all())
                dfs.append(grouped)

        if not dfs:
            legacy_file = iter_dir / "parameters.parquet"
            if legacy_file.exists():
                return pl.read_parquet(legacy_file)
            msg = "Parameters not found."
            raise FileNotFoundError(msg)

        result = dfs[0]
        for df in dfs[1:]:
            result = result.join(df, on="realization", how="full")
        return result

    def write_parameters(
        self,
        experiment_id: str,
        execution_id: str,
        iteration: int,
        parameters: pl.DataFrame,
    ) -> None:
        """Write the parameter matrix back to partitioned schema storage."""
        iter_dir = (
            self._base_storage_path / experiment_id / execution_id / f"iter-{iteration}"
        )
        param_dir = iter_dir / "parameters"
        param_dir.mkdir(parents=True, exist_ok=True)

        template_files = list(param_dir.glob("*.parquet"))
        if not template_files:
            template_files = list(iter_dir.glob("parameters_*.parquet"))

        for filepath in template_files:
            prior_df = pl.read_parquet(filepath)

            update_cols = [
                c
                for c in prior_df.columns
                if c in parameters.columns and c != "realization"
            ]

            if not update_cols:
                continue

            primary_keys = [
                c
                for c in prior_df.columns
                if c not in update_cols and c != "realization"
            ]

            if not primary_keys:
                updated = parameters.select(["realization", *update_cols])
                prior_df = prior_df.drop(update_cols).join(
                    updated,
                    on="realization",
                    how="left",
                )
            else:
                prior_df = prior_df.sort(primary_keys)
                exploded = parameters.select(["realization", *update_cols]).explode(
                    update_cols,
                )
                prior_df = prior_df.with_columns(
                    [exploded[col].alias(col) for col in update_cols],
                )

            prior_df.write_parquet(filepath)

        parameters.write_parquet(iter_dir / "parameters.parquet")

    def get_step_log(
        self,
        experiment_id: str,
        execution_id: str,
        iteration: int,
        realization_id: int,
        step_name: str,
        log_type: str = "stdout",
    ) -> str:
        """Retrieve the stdout or stderr log for a specific step.

        Args:
            experiment_id: The ID of the experiment.
            execution_id: The unique ID of the execution.
            iteration: The iteration number.
            realization_id: The realization ID.
            step_name: The name of the forward model step.
            log_type: Either 'stdout' or 'stderr'.

        Returns:
            The content of the log file.
        """
        log_file = (
            self._base_storage_path
            / experiment_id
            / execution_id
            / f"iter-{iteration}"
            / "logs"
            / f"realization-{realization_id}"
            / f"{step_name}.{log_type}"
        )
        if not log_file.exists():
            return ""
        return log_file.read_text(encoding="utf-8")

    def write_step_log(
        self,
        experiment_id: str,
        execution_id: str,
        iteration: int,
        realization_id: int,
        step_name: str,
        content: str,
        log_type: str = "stdout",
    ) -> None:
        """Write a stdout or stderr log for a specific step.

        Args:
            experiment_id: The ID of the experiment.
            execution_id: The unique ID of the execution.
            iteration: The iteration number.
            realization_id: The realization ID.
            step_name: The name of the forward model step.
            content: The log content to write.
            log_type: Either 'stdout' or 'stderr'.
        """
        log_dir = (
            self._base_storage_path
            / experiment_id
            / execution_id
            / f"iter-{iteration}"
            / "logs"
            / f"realization-{realization_id}"
        )
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{step_name}.{log_type}"
        log_file.write_text(content, encoding="utf-8")

    def write_experiment_config(self, config: ExperimentConfig) -> None:
        """Write the experiment config to disk."""
        exp_dir = self._base_storage_path / config.name
        exp_dir.mkdir(parents=True, exist_ok=True)
        config_file = exp_dir / "config.json"
        config_file.write_text(config.model_dump_json(indent=2))

    def write_execution_state(
        self,
        experiment_name: str,
        execution_id: str,
        state_data: ExecutionState,
    ) -> None:
        """Write the orchestrator's execution state to disk."""
        state_dir = self._base_storage_path / experiment_name / execution_id
        state_dir.mkdir(parents=True, exist_ok=True)
        state_file = state_dir / "execution_state.json"

        state_file.write_text(state_data.model_dump_json(indent=2))

    async def consolidate(self, experiment_id: str, execution_id: str) -> None:
        """Manually trigger consolidation for an experiment/execution."""
        execution_dir = self._base_storage_path / experiment_id / execution_id
        if not execution_dir.exists():
            return

        for ensemble_path in execution_dir.iterdir():
            if not ensemble_path.is_dir():
                continue

            worker = ConsolidationWorker.get_instance(ensemble_path)
            await worker.consolidate()

    def get_manifest(
        self,
        experiment_id: str,
        execution_id: str,
        iteration: int,
    ) -> dict[str, float]:
        """Lightweight cache-busting endpoint returning modification timestamps."""
        iter_dir = (
            self._base_storage_path / experiment_id / execution_id / f"iter-{iteration}"
        )
        manifest = {}

        params_file = iter_dir / "parameters.parquet"
        if params_file.exists():
            manifest["parameters"] = params_file.stat().st_mtime

        resps_dir = iter_dir / "responses"
        if resps_dir.exists():
            parquet_files = list(resps_dir.glob("*.parquet"))
            if parquet_files:
                manifest["responses"] = max(f.stat().st_mtime for f in parquet_files)
            else:
                manifest["responses"] = resps_dir.stat().st_mtime

        return manifest
