"""Ingestion receiver for GERT storage."""

import json
from pathlib import Path

from gert.experiments.models import IngestionPayload


class IngestionReceiver:
    """Receives ingestion payloads and appends them to a fast .jsonl queue.

    Designed for high-throughput push-based data ingestion.
    """

    def __init__(self, base_storage_path: Path) -> None:
        """Initialize the receiver with a base storage path.

        Args:
            base_storage_path: The root directory for storing ingestion queues.
        """
        self._base_storage_path = base_storage_path
        self._base_storage_path.mkdir(parents=True, exist_ok=True)

    def receive(
        self,
        experiment_id: str,
        execution_id: str,
        iteration: int,
        payload: IngestionPayload,
    ) -> None:
        """Append an ingestion payload to the experiment ensemble's .jsonl queue.

        Args:
            experiment_id: The ID of the experiment.
            execution_id: The unique ID of the execution.
            iteration: The iteration number.
            payload: The ingestion payload to store.

        Raises:
            TypeError: If the payload is not a Pydantic model.
        """
        queue_dir = (
            self._base_storage_path / experiment_id / execution_id / f"iter-{iteration}"
        )
        queue_dir.mkdir(parents=True, exist_ok=True)

        queue_file = queue_dir / "ingestion_queue.jsonl"

        # Serialize using Pydantic's model_dump(mode="json")
        # Handle the Union by accessing model_dump if it's a BaseModel
        if hasattr(payload, "model_dump"):
            data = payload.model_dump(mode="json")
        else:
            # This should not happen if IngestionPayload is a Union of BaseModels
            msg = f"Payload must be a Pydantic model, got: {type(payload)}"
            raise TypeError(msg)

        with queue_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(data) + "\n")
