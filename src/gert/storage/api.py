"""Query API for GERT storage."""

from pathlib import Path

import polars as pl

from gert.storage.consolidation import ConsolidationWorker


class StorageAPI:
    """Provides methods to query consolidated experiment data."""

    def __init__(self, base_storage_path: Path) -> None:
        """Initialize the query API with a base storage path."""
        self._base_storage_path = base_storage_path

    def flush(self, experiment_id: str, execution_id: str, iteration: int) -> bool:
        """Forces the Consolidator to drain the queue entirely before returning."""
        worker = ConsolidationWorker(self._base_storage_path)
        queue_dir = (
            self._base_storage_path / experiment_id / execution_id / f"iter-{iteration}"
        )

        if queue_dir.exists():
            worker.consolidate_ensemble(queue_dir)
        return True

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
