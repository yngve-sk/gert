"""Standardized client SDK for GERT forward models."""

import logging
import sys
import time
import traceback
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import httpx

from gert.experiments.models import ResponsePayload

logger = logging.getLogger(__name__)


class GertForwardModelClient:
    """Standardized GERT client for forward models to report data and status."""

    def __init__(
        self,
        api_url: str,
        experiment_id: str,
        execution_id: str,
        iteration: int,
        realization_id: int,
        source_step: str,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.experiment_id = experiment_id
        self.execution_id = execution_id
        self.iteration = iteration
        self.realization_id = realization_id
        self.source_step = source_step
        self._client = httpx.Client(
            base_url=self.api_url,
            timeout=httpx.Timeout(120.0, connect=10.0),
            limits=httpx.Limits(max_connections=None, max_keepalive_connections=None),
        )

    def _post_with_retry(
        self,
        endpoint: str,
        json_data: dict[str, Any],
        max_retries: int = 5,
    ) -> httpx.Response:
        """Post data to the server with exponential backoff retries.

        Raises:
            httpx.HTTPError: If the request permanently fails.
        """
        delay = 2.0
        last_exception: Exception | None = None

        for i in range(max_retries):
            try:
                resp = self._client.post(endpoint, json=json_data)
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                # E.g. 404 Not Found, usually not retryable but we retry just in case
                # server is restarting.
                last_exception = e
                logger.exception(
                    f"HTTP {e.response.status_code} for {endpoint}: "
                    f"Response text: {e.response.text}. Retrying in {delay}s...",
                )
                time.sleep(delay)
                delay *= 2
            except httpx.RequestError as e:
                # E.g. ConnectTimeout
                last_exception = e
                logger.exception(
                    f"Attempt {i + 1}/{max_retries} failed for {endpoint}."
                    f"Retrying in {delay}s...",
                )
                time.sleep(delay)
                delay *= 2
            except Exception as e:
                last_exception = e
                logger.exception(
                    f"Attempt {i + 1}/{max_retries} unexpected fail for {endpoint}. "
                    f"Retrying in {delay}s...",
                )
                time.sleep(delay)
                delay *= 2
            else:
                return resp

        msg = f"Permanent failure after {max_retries} attempts for {endpoint}"
        logger.error(msg)
        if last_exception:
            raise last_exception
        raise httpx.HTTPError(msg)

    def post_response(self, key: dict[str, str], value: float) -> None:
        """Ingest a single response value."""
        payload = ResponsePayload(
            realization=self.realization_id,
            source_step=self.source_step,
            key=key,
            value=value,
        )
        endpoint = (
            f"/api/experiments/{self.experiment_id}/executions/"
            f"{self.execution_id}/ensembles/{self.iteration}/ingest"
        )
        self._post_with_retry(endpoint, payload.model_dump())

    def mark_complete(self) -> None:
        """Explicitly signal that this realization has finished successfully."""
        endpoint = (
            f"/api/experiments/{self.experiment_id}/executions/{self.execution_id}/"
            f"ensembles/{self.iteration}/realizations/{self.realization_id}/complete"
        )
        # We can send an empty body or some metadata if needed
        self._post_with_retry(endpoint, {"source_step": self.source_step})

    def mark_failed(self, error_message: str, traceback_str: str | None = None) -> None:
        """Explicitly signal that this realization has failed."""
        endpoint = (
            f"/api/experiments/{self.experiment_id}/executions/{self.execution_id}/"
            f"ensembles/{self.iteration}/realizations/{self.realization_id}/fail"
        )
        payload = {
            "source_step": self.source_step,
            "error": error_message,
            "traceback": traceback_str,
        }
        self._post_with_retry(endpoint, payload)

    @contextmanager
    def run(self) -> Generator[None]:
        """Context manager to automatically signal completion or failure."""
        try:
            yield
            self.mark_complete()
        except Exception as e:  # noqa: BLE001
            tb = traceback.format_exc()
            try:
                self.mark_failed(str(e), tb)
            except Exception:
                logger.exception("Failed to report failure to server")

            # Exit with non-zero code to signal failure to PSI/J
            print(f"Forward model failed: {e}", file=sys.stderr)  # noqa: T201
            sys.exit(1)

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()
