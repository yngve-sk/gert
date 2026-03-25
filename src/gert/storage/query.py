"""Query API for GERT storage."""

from pathlib import Path

import polars as pl


class StorageQueryAPI:
    """Provides methods to query consolidated experiment data."""

    def __init__(self, base_storage_path: Path) -> None:
        """Initialize the query API with a base storage path.

        Args:
            base_storage_path: The root directory for experiment data.
        """
        self._base_storage_path = base_storage_path

    def get_responses(
        self,
        experiment_name: str,
        execution_id: str,
        iteration: int,
    ) -> pl.DataFrame:
        """Retrieve all consolidated responses for an experiment and iteration.

        Args:
            experiment_name: The name of the experiment.
            execution_id: The unique ID of the execution.
            iteration: The iteration number.

        Returns:
            A polars DataFrame containing the experiment responses.

        Raises:
            FileNotFoundError: If the experiment, iteration, or its consolidated
                data doesn't exist.
        """
        parquet_file = (
            self._base_storage_path
            / experiment_name
            / execution_id
            / f"iter-{iteration}"
            / "responses.parquet"
        )

        if not parquet_file.exists():
            msg = (
                f"Consolidated data for experiment '{experiment_name}', "
                f"execution '{execution_id}', and iteration '{iteration}' not found."
            )
            raise FileNotFoundError(msg)

        return pl.read_parquet(parquet_file)
