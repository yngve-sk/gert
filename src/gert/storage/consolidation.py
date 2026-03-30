"""Consolidation worker for GERT storage."""

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

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

    def consolidate(self, experiment_id: str, execution_id: str) -> None:
        """Drain the .jsonl queue and upsert data into the .parquet response files.

        Processes all ensemble (iteration) directories within the execution.

        Args:
            experiment_id: The ID of the experiment.
            execution_id: The unique ID of the execution.
        """
        execution_dir = self._base_storage_path / experiment_id / execution_id
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
        """Read ingestion queue, route data to schema-specific tables, and update registry."""  # noqa: E501
        queue_file = queue_dir / "ingestion_queue.jsonl"
        if not queue_file.exists() or queue_file.stat().st_size == 0:
            return

        # 1. Protect queue from concurrent ingestion
        processing_file = queue_dir / "processing_queue.jsonl"
        queue_file.rename(processing_file)

        try:
            # 2. Parse heterogeneous JSONL records
            with Path(processing_file).open("r", encoding="utf-8") as f:
                records = [json.loads(line) for line in f]

            # Map each record to its schema-specific bucket
            # Key = tuple of sorted dimension keys
            buckets: dict[tuple[str, ...], list[dict[str, Any]]] = {}

            for rec in records:
                # Unnest 'key' dict and realization
                flat = {"realization": rec["realization"], "value": rec["value"]}
                dims = []
                if isinstance(rec["key"], dict):
                    for k, v in rec["key"].items():
                        flat[k] = v
                        dims.append(k)
                else:
                    # Handle legacy or simple string keys
                    flat["key"] = rec["key"]
                    dims.append("key")

                schema_key = tuple(sorted(dims))
                if schema_key not in buckets:
                    buckets[schema_key] = []
                buckets[schema_key].append(flat)

            # 3. Process each bucket (One Table per Schema)
            resp_dir = queue_dir / "responses"
            resp_dir.mkdir(exist_ok=True)

            for schema_key, schema_records in buckets.items():
                df_new = pl.DataFrame(schema_records)

                # Deterministic filename based on schema
                schema_hash = hashlib.sha256("".join(schema_key).encode()).hexdigest()[
                    :8
                ]
                table_name = f"data_{schema_hash}.parquet"

                parquet_file = resp_dir / table_name
                primary_keys = list(schema_key)

                # Join/Upsert logic
                if parquet_file.exists():
                    df_existing = pl.read_parquet(parquet_file)
                    # Merge and keep latest value per realization+coords
                    consolidated = pl.concat([df_existing, df_new], how="diagonal")
                    consolidated = consolidated.unique(
                        subset=["realization", *primary_keys],
                        keep="last",
                    )
                else:
                    consolidated = df_new

                consolidated.write_parquet(parquet_file)

        finally:
            processing_file.unlink()
