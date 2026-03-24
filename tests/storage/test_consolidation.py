from pathlib import Path

import polars as pl

from gert.experiments.models import ResponsePayload
from gert.storage.consolidation import ConsolidationWorker
from gert.storage.ingestion import IngestionReceiver


def test_consolidation_worker_creates_parquet(tmp_path: Path) -> None:
    """Test that ConsolidationWorker drains .jsonl and creates .parquet."""
    base_path = tmp_path / "gert_storage"
    receiver = IngestionReceiver(base_path)
    worker = ConsolidationWorker(base_path)
    experiment_id = "test-exp"

    # 1. Receive data
    payload = ResponsePayload(
        realization=0,
        source_step="step1",
        key={"response": "FOPR"},
        value=100.0,
    )
    receiver.receive(experiment_id, payload)

    queue_file = base_path / experiment_id / "ingestion_queue.jsonl"
    parquet_file = base_path / experiment_id / "responses.parquet"
    assert queue_file.exists()
    assert not parquet_file.exists()

    # 2. Consolidate
    worker.consolidate(experiment_id)

    assert not queue_file.exists()
    assert parquet_file.exists()

    # 3. Verify parquet content
    df = pl.read_parquet(parquet_file)
    expected = [
        {
            "realization": 0,
            "source_step": "step1",
            "key": {"response": "FOPR"},
            "value": 100.0,
        },
    ]
    assert df.to_dicts() == expected


def test_consolidation_worker_appends_to_parquet(tmp_path: Path) -> None:
    """Test that ConsolidationWorker appends new data to existing .parquet."""
    base_path = tmp_path / "gert_storage"
    receiver = IngestionReceiver(base_path)
    worker = ConsolidationWorker(base_path)
    experiment_id = "test-exp"

    # First round
    receiver.receive(
        experiment_id,
        ResponsePayload(
            realization=0,
            source_step="step1",
            key={"response": "FOPR"},
            value=100.0,
        ),
    )
    worker.consolidate(experiment_id)

    # Second round
    receiver.receive(
        experiment_id,
        ResponsePayload(
            realization=1,
            source_step="step1",
            key={"response": "FOPR"},
            value=105.0,
        ),
    )
    worker.consolidate(experiment_id)

    parquet_file = base_path / experiment_id / "responses.parquet"
    df = pl.read_parquet(parquet_file)
    expected = [
        {
            "realization": 0,
            "source_step": "step1",
            "key": {"response": "FOPR"},
            "value": 100.0,
        },
        {
            "realization": 1,
            "source_step": "step1",
            "key": {"response": "FOPR"},
            "value": 105.0,
        },
    ]
    assert df.to_dicts() == expected
