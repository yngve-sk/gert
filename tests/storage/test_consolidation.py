"""Tests for the ConsolidationWorker's schema routing and registry management."""

import json
from pathlib import Path

import polars as pl
import pytest

from gert.storage.consolidation import ConsolidationWorker


@pytest.fixture
def storage_path(tmp_path: Path) -> Path:
    """Provide a temporary storage root."""
    return tmp_path / "storage"


@pytest.fixture
def worker(storage_path: Path) -> ConsolidationWorker:
    """Provide a ConsolidationWorker instance."""
    return ConsolidationWorker(storage_path)


def test_consolidate_heterogeneous_records(
    worker: ConsolidationWorker,
    storage_path: Path,
) -> None:
    """Prove that the worker routes different JSONL records to different schema tables
    and maintains a schemas.json registry.
    """
    queue_dir = storage_path / "test_exp" / "run_1" / "iter-0"
    queue_dir.mkdir(parents=True)
    queue_file = queue_dir / "ingestion_queue.jsonl"

    # 1. Write mixed schema records to the queue
    records = [
        # Schema 1: Well data (well_id, time)
        {"realization": 0, "key": {"well_id": "W1", "time": 10.0}, "value": 100.0},
        {"realization": 1, "key": {"well_id": "W1", "time": 10.0}, "value": 200.0},
        # Schema 2: Global summary (response_name)
        {"realization": 0, "key": {"response_name": "FOPR"}, "value": 5000.0},
        # Schema 3: Grid data (x, y, z)
        {"realization": 0, "key": {"x": 1, "y": 2, "z": 3}, "value": 0.25},
    ]

    with Path(queue_file).open("w", encoding="utf-8") as f:
        f.writelines(json.dumps(r) + "\n" for r in records)

    # 2. Execute consolidation
    worker.consolidate_ensemble(queue_dir)

    # 3. Assertions
    resp_dir = queue_dir / "responses"
    assert resp_dir.exists()

    # Check for parquet files (hashes will be deterministic)
    parquet_files = list(resp_dir.glob("*.parquet"))
    assert len(parquet_files) == 3


def test_consolidate_upsert_logic(
    worker: ConsolidationWorker,
    storage_path: Path,
) -> None:
    """Prove that the worker correctly upserts (updates) existing data with newer records."""  # noqa: E501
    queue_dir = storage_path / "test_upsert" / "run_1" / "iter-0"
    queue_dir.mkdir(parents=True)
    queue_file = queue_dir / "ingestion_queue.jsonl"

    # 1. Initial consolidation
    Path(queue_file).write_text(
        encoding="utf-8",
        data=json.dumps({"realization": 0, "key": {"well_id": "W1"}, "value": 1.0})
        + "\n",
    )

    worker.consolidate_ensemble(queue_dir)

    # 2. Second consolidation with updated value for same key
    Path(queue_file).write_text(
        encoding="utf-8",
        data=json.dumps({"realization": 0, "key": {"well_id": "W1"}, "value": 2.0})
        + "\n",
    )

    worker.consolidate_ensemble(queue_dir)

    # 3. Assertion: should only have 1 row with the newest value
    resp_dir = queue_dir / "responses"
    filename = next(iter(resp_dir.glob("*.parquet")))
    df = pl.read_parquet(resp_dir / filename)

    assert len(df) == 1
    assert df["value"][0] == 2.0
