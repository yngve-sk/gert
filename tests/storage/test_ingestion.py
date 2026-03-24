import json
from pathlib import Path

from gert.experiments.models import ResponsePayload
from gert.storage.ingestion import IngestionReceiver


def test_ingestion_receiver_appends_to_jsonl(tmp_path: Path) -> None:
    """Test that IngestionReceiver correctly appends payloads to a .jsonl file."""
    base_path = tmp_path / "gert_storage"
    receiver = IngestionReceiver(base_path)
    experiment_id = "test-exp"

    payload1 = ResponsePayload(
        realization=0,
        source_step="step1",
        key={"response": "FOPR"},
        value=100.0,
    )

    payload2 = ResponsePayload(
        realization=1,
        source_step="step1",
        key={"response": "FOPR"},
        value=105.0,
    )

    receiver.receive(experiment_id, payload1)
    receiver.receive(experiment_id, payload2)

    queue_file = base_path / experiment_id / "ingestion_queue.jsonl"
    assert queue_file.exists()

    with queue_file.open("r", encoding="utf-8") as f:
        lines = f.readlines()

    assert len(lines) == 2
    assert json.loads(lines[0]) == payload1.model_dump(mode="json")
    assert json.loads(lines[1]) == payload2.model_dump(mode="json")
