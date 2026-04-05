"""Ingestion receiver for GERT storage."""

import json
import logging
from pathlib import Path

from gert.experiments.models import IngestionPayload


def _get_ingestion_logger() -> logging.Logger:
    """Configure and return a dedicated logger for data ingestion."""
    Path("logs").mkdir(exist_ok=True, parents=True)
    logger = logging.getLogger("gert.ingestion")

    # Only configure if no handlers are present
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        logger.propagate = False

        # Dedicated ingestion log
        fh = logging.FileHandler("logs/data_ingestion.log")
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(fh)

        # Combined log
        ch = logging.FileHandler("logs/combined.log", mode="a")
        ch.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s"),
        )
        logger.addHandler(ch)

    return logger


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
        self._logger = _get_ingestion_logger()
        self._logger.info(
            f"IngestionReceiver initialized for storage: {self._base_storage_path}",
        )

    def receive(
        self,
        experiment_id: str,
        execution_id: str,
        iteration: int,
        payload: IngestionPayload,
    ) -> None:
        """
        Append an ingestion payload to the experiment
        ensemble's .jsonl queue.

        Raises:
            TypeError: If the payload is not an instance of IngestionPayload.
        """
        ensemble_path = (
            self._base_storage_path / experiment_id / execution_id / f"iter-{iteration}"
        )
        ensemble_path.mkdir(parents=True, exist_ok=True)

        queue_file = ensemble_path / "ingestion_queue.jsonl"

        if hasattr(payload, "model_dump"):
            data = payload.model_dump(mode="json")
        else:
            msg = f"Payload must be a Pydantic model, got: {type(payload)}"
            raise TypeError(msg)

        self._logger.info(
            f"Received payload for Exp: {experiment_id}, Exec: {execution_id}, "
            f"Iter: {iteration}, Realization: {data.get('realization')}, "
            f"Source Step: {data.get('source_step')}",
        )

        with queue_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(data) + "\n")
