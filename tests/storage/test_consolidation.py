from pathlib import Path

import polars as pl

from gert.experiments.models import ResponsePayload
from gert.storage.consolidation import ConsolidationWorker
from gert.storage.ingestion import IngestionReceiver


def test_consolidation_worker_creates_parquet(tmp_path: Path) -> None:
    """Test that ConsolidationWorker drains .jsonl and creates .parquet."""
    base_path = tmp_path / "permanent_storage"
    receiver = IngestionReceiver(base_path)
    worker = ConsolidationWorker(base_path)
    experiment_id = "test-exp"
    ensemble_id = "ens-0"

    # 1. Receive data
    payload = ResponsePayload(
        realization=0,
        source_step="step1",
        key={"response": "FOPR"},
        value=100.0,
    )
    receiver.receive(experiment_id, ensemble_id, payload)

    queue_file = base_path / experiment_id / ensemble_id / "ingestion_queue.jsonl"
    parquet_file = base_path / experiment_id / ensemble_id / "responses.parquet"
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
            "response": "FOPR",
            "value": 100.0,
        },
    ]
    assert df.to_dicts() == expected


def test_consolidation_worker_appends_to_parquet(tmp_path: Path) -> None:
    """Test that ConsolidationWorker appends new data to existing .parquet."""
    base_path = tmp_path / "permanent_storage"
    receiver = IngestionReceiver(base_path)
    worker = ConsolidationWorker(base_path)
    experiment_id = "test-exp"
    ensemble_id = "ens-0"

    # First round
    receiver.receive(
        experiment_id,
        ensemble_id,
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
        ensemble_id,
        ResponsePayload(
            realization=1,
            source_step="step1",
            key={"response": "FOPR"},
            value=105.0,
        ),
    )
    worker.consolidate(experiment_id)

    parquet_file = base_path / experiment_id / ensemble_id / "responses.parquet"
    df = pl.read_parquet(parquet_file)
    expected = [
        {
            "realization": 0,
            "source_step": "step1",
            "response": "FOPR",
            "value": 100.0,
        },
        {
            "realization": 1,
            "source_step": "step1",
            "response": "FOPR",
            "value": 105.0,
        },
    ]
    assert df.to_dicts() == expected


def test_consolidate_nonexistent_experiment(tmp_path: Path) -> None:
    """Test consolidation handles non-existent experiment directory gracefully."""
    base_path = tmp_path / "permanent_storage"
    worker = ConsolidationWorker(base_path)
    # Should just return early without error
    worker.consolidate("nonexistent-exp")


def test_consolidate_ignores_files(tmp_path: Path) -> None:
    """Test consolidation ignores files that are not directories in experiment dir."""
    base_path = tmp_path / "permanent_storage"
    worker = ConsolidationWorker(base_path)
    experiment_id = "test-exp-files"

    exp_dir = base_path / experiment_id
    exp_dir.mkdir(parents=True)

    # Create a regular file instead of a directory
    not_a_dir = exp_dir / "not_a_dir.txt"
    not_a_dir.write_text("hello")

    # Should not crash, just ignore the file
    worker.consolidate(experiment_id)


def test_consolidate_missing_queue_file(tmp_path: Path) -> None:
    """Test consolidation skips ensemble directories with missing queue files."""
    base_path = tmp_path / "permanent_storage"
    worker = ConsolidationWorker(base_path)
    experiment_id = "test-exp-no-queue"
    ensemble_id = "ens-no-queue"

    queue_dir = base_path / experiment_id / ensemble_id
    queue_dir.mkdir(parents=True)

    # Intentionally do not create ingestion_queue.jsonl
    # Should not crash, just return early
    worker.consolidate(experiment_id)
