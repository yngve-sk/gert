import json
from pathlib import Path

import pytest

from gert.experiments.models import ResponsePayload
from gert.storage.ingestion import IngestionReceiver


def test_ingestion_receiver_appends_to_jsonl(tmp_path: Path) -> None:
    """Test that IngestionReceiver correctly appends payloads to a .jsonl file."""
    base_path = tmp_path / "permanent_storage"
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

    ensemble_id = "ens-0"
    receiver.receive(experiment_id, ensemble_id, payload1)
    receiver.receive(experiment_id, ensemble_id, payload2)

    queue_file = base_path / experiment_id / ensemble_id / "ingestion_queue.jsonl"
    assert queue_file.exists()
    with queue_file.open("r", encoding="utf-8") as f:
        lines = f.readlines()

    assert len(lines) == 2
    assert json.loads(lines[0]) == payload1.model_dump(mode="json")
    assert json.loads(lines[1]) == payload2.model_dump(mode="json")


def test_ingestion_receiver_raises_on_invalid_payload(tmp_path: Path) -> None:
    """Test that IngestionReceiver raises TypeError on non-Pydantic payload."""
    base_path = tmp_path / "permanent_storage"
    receiver = IngestionReceiver(base_path)
    experiment_id = "test-exp"
    ensemble_id = "ens-invalid"

    # A dictionary instead of a Pydantic model
    invalid_payload = {"realization": 0, "value": 100}

    with pytest.raises(TypeError, match="Payload must be a Pydantic model"):
        receiver.receive(experiment_id, ensemble_id, invalid_payload)  # type: ignore[arg-type]
