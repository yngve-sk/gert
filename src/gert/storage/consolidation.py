"""Consolidation worker for GERT storage."""

import asyncio
from pathlib import Path

import polars as pl


class ConsolidationWorker:
    """Background worker that consolidates .jsonl ingestion queues into .parquet files.

    Uses polars for high-performance columnar data processing.
    """

    def __init__(self, base_storage_path: Path) -> None:
        """Initialize the worker with a base storage path.

        Args:
            base_storage_path: The root directory for storing ingestion queues.
        """
        self._base_storage_path = base_storage_path

    def consolidate(self, experiment_name: str, execution_id: str) -> None:
        """Drain the .jsonl queue and upsert data into the .parquet response files.

        Processes all ensemble (iteration) directories within the execution.

        Args:
            experiment_name: The name of the experiment.
            execution_id: The unique ID of the execution.
        """
        execution_dir = self._base_storage_path / experiment_name / execution_id
        if not execution_dir.exists():
            return

        for queue_dir in execution_dir.iterdir():
            if not queue_dir.is_dir():
                continue

            self.consolidate_ensemble(queue_dir)

    async def start_watching(
        self,
        queue_path: Path,
        interval: float = 5.0,
    ) -> None:
        """Continuously drain the .jsonl queue at the specified interval.

        Args:
            queue_path: The path to the .jsonl ingestion queue.
            interval: The interval in seconds to wait between consolidations.
        """
        while True:
            await asyncio.sleep(interval)
            # Find the parent queue_dir that contains these files
            # to reuse the existing method. In interfaces.md it mentions
            # taking queue_path and parquet_path, but consolidate_ensemble
            # takes queue_dir. We can adapt it here.
            queue_dir = queue_path.parent
            if queue_dir.exists():
                self.consolidate_ensemble(queue_dir)

    def consolidate_ensemble(self, queue_dir: Path) -> None:
        queue_file = queue_dir / "ingestion_queue.jsonl"
        parquet_file = queue_dir / "responses.parquet"

        if not queue_file.exists():
            return

        # Rename the queue file first to avoid data loss
        processing_file = queue_dir / "processing_queue.jsonl"
        queue_file.rename(processing_file)

        # Read new data from the .jsonl queue
        new_data_df = pl.read_ndjson(processing_file)

        # Flatten the 'key' dictionary if it exists
        if "key" in new_data_df.columns and isinstance(
            new_data_df.schema["key"],
            pl.Struct,
        ):
            new_data_df = new_data_df.unnest("key")

        # Load existing data if it exists
        if parquet_file.exists():
            existing_df = pl.read_parquet(parquet_file)
            consolidated_df = pl.concat([existing_df, new_data_df])
        else:
            consolidated_df = new_data_df

        # Write back to parquet
        consolidated_df.write_parquet(parquet_file)

        # Truncate the queue file after successful consolidation
        # In a real system, we should use a more robust draining mechanism
        # (e.g., renaming the queue file first) to avoid data loss.
        processing_file.unlink()
