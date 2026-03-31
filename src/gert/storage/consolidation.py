"""Consolidation worker for GERT storage."""

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, ClassVar

import polars as pl

logger = logging.getLogger(__name__)


class ConsolidationWorker:
    """Background worker that consolidates .jsonl ingestion queues into .parquet files.

    Uses polars for high-performance columnar data processing.
    Ensures a single instance per ensemble_path via a registry.
    """

    _registry: ClassVar[dict[Path, "ConsolidationWorker"]] = {}

    @classmethod
    def get_instance(cls, ensemble_path: Path) -> "ConsolidationWorker":
        """Get or create the singleton worker for a specific ensemble path."""
        abs_path = ensemble_path.resolve()
        if abs_path not in cls._registry:
            cls._registry[abs_path] = cls(abs_path)
        return cls._registry[abs_path]

    def __init__(self, ensemble_path: Path) -> None:
        """Initialize the worker with an ensemble path.

        Use ConsolidationWorker.get_instance() instead of direct instantiation.
        """
        self._ensemble_path = ensemble_path
        self._lock = asyncio.Lock()

    async def start_watching(
        self,
        interval: float = 5.0,
    ) -> None:
        """Continuously drain the .jsonl queue at the specified interval.

        Args:
            interval: The interval in seconds to wait between consolidations.

        Raises:
            asyncio.CancelledError: If the watcher task is cancelled.
        """
        try:
            while True:
                await asyncio.sleep(interval)
                if self._ensemble_path.exists():
                    await self.consolidate()
        except asyncio.CancelledError:
            # Final consolidation attempt on cancellation
            if self._ensemble_path.exists():
                await self.consolidate()
            raise

    async def consolidate(self) -> None:
        """Read ingestion queue and route data to schema-specific tables."""
        async with self._lock:
            queue_file = self._ensemble_path / "ingestion_queue.jsonl"
            if not queue_file.exists() or queue_file.stat().st_size == 0:
                return

            logger.info(f"Consolidation started: {self._ensemble_path}")

            processing_file = self._ensemble_path / "processing_queue.jsonl"
            try:
                queue_file.rename(processing_file)
            except OSError:
                logger.exception(f"Failed to rename queue file {queue_file}")
                return

            try:
                records = await self._parse_jsonl_file(processing_file)
                if not records:
                    return

                buckets = self._group_records_by_schema(records)
                self._process_buckets(buckets)

            except Exception:
                logger.exception("Unexpected error during consolidation")
                raise
            finally:
                if processing_file.exists():
                    try:
                        processing_file.unlink()
                    except OSError:
                        logger.exception(f"Failed to delete {processing_file}")

    def _group_records_by_schema(
        self,
        records: list[dict[str, Any]],
    ) -> dict[tuple[str, ...], list[dict[str, Any]]]:
        """Group ingestion records by their schema (sorted keys)."""
        buckets: dict[tuple[str, ...], list[dict[str, Any]]] = {}

        for rec in records:
            try:
                flat = {
                    "realization": rec["realization"],
                    "value": rec["value"],
                }
                dims = []
                if isinstance(rec["key"], dict):
                    for k, v in rec["key"].items():
                        flat[k] = v
                        dims.append(k)
                else:
                    flat["key"] = rec["key"]
                    dims.append("key")

                schema_key = tuple(sorted(dims))
                if schema_key not in buckets:
                    buckets[schema_key] = []
                buckets[schema_key].append(flat)
            except KeyError:
                msg = f"Missing required key in record. Record: {rec}"
                logger.exception(msg)
                continue

        return buckets

    def _process_buckets(
        self,
        buckets: dict[tuple[str, ...], list[dict[str, Any]]],
    ) -> None:
        """Write grouped records to their respective schema-specific parquet files."""
        resp_dir = self._ensemble_path / "responses"
        resp_dir.mkdir(exist_ok=True)

        for schema_key, schema_records in buckets.items():
            try:
                df_new = pl.DataFrame(schema_records)
                schema_hash = hashlib.sha256("".join(schema_key).encode()).hexdigest()[
                    :8
                ]
                parquet_file = resp_dir / f"data_{schema_hash}.parquet"

                if parquet_file.exists():
                    df_existing = pl.read_parquet(parquet_file)
                    consolidated = pl.concat([df_existing, df_new], how="diagonal")
                    consolidated = consolidated.unique(
                        subset=["realization", *schema_key],
                        keep="last",
                    )
                else:
                    consolidated = df_new

                consolidated.write_parquet(parquet_file)
                logger.debug(f"Updated {parquet_file} ({len(schema_records)} records)")
            except Exception:
                logger.exception(f"Error processing bucket {schema_key}")

    async def _parse_jsonl_file(self, file_path: Path) -> list[dict[str, Any]]:
        """Read and parse a JSONL file in a thread pool to avoid blocking."""

        def _read_and_parse() -> list[dict[str, Any]]:
            records = []
            with file_path.open("r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        logger.exception(
                            f"JSON decode error in {file_path} line {line_num}",
                        )
                        continue
            return records

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _read_and_parse)
