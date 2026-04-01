"""Tests for the GertClient SDK."""

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import httpx
import pytest

from gert.plugins.forward_model_client import GertForwardModelClient


@pytest.fixture
def mock_httpx_client() -> Generator[MagicMock]:
    with patch("httpx.Client") as mock:
        yield mock.return_value


@pytest.fixture
def gert_client(mock_httpx_client: MagicMock) -> GertForwardModelClient:
    return GertForwardModelClient(
        api_url="http://localhost:8000",
        experiment_id="exp-1",
        execution_id="run-1",
        iteration=0,
        realization_id=42,
        source_step="test-step",
    )


def test_ingest_response(
    gert_client: GertForwardModelClient,
    mock_httpx_client: MagicMock,
) -> None:
    mock_httpx_client.post.return_value = MagicMock(status_code=200)

    gert_client.post_response({"response": "well", "well": "W1"}, 123.45)

    assert mock_httpx_client.post.called
    args, kwargs = mock_httpx_client.post.call_args
    assert "/ensembles/0/ingest" in args[0]
    payload = kwargs["json"]
    assert payload["realization"] == 42
    assert payload["key"] == {"response": "well", "well": "W1"}
    assert payload["value"] == 123.45


def test_run_context_manager_success(
    gert_client: GertForwardModelClient,
    mock_httpx_client: MagicMock,
) -> None:
    mock_httpx_client.post.return_value = MagicMock(status_code=200)

    with gert_client.run():
        pass  # Do nothing

    # Should have called complete
    assert mock_httpx_client.post.call_count == 1
    args, _ = mock_httpx_client.post.call_args
    assert "/realizations/42/complete" in args[0]


def test_run_context_manager_failure(
    gert_client: GertForwardModelClient,
    mock_httpx_client: MagicMock,
) -> None:
    mock_httpx_client.post.return_value = MagicMock(status_code=200)

    msg = "Boom!"
    with pytest.raises(SystemExit) as excinfo, gert_client.run():
        raise ValueError(msg)

    assert excinfo.value.code == 1

    # Should have called fail
    assert mock_httpx_client.post.call_count == 1
    args, kwargs = mock_httpx_client.post.call_args
    assert "/realizations/42/fail" in args[0]
    payload = kwargs["json"]
    assert "Boom!" in payload["error"]
    assert "traceback" in payload
    assert payload["traceback"] is not None


def test_retry_logic(
    gert_client: GertForwardModelClient,
    mock_httpx_client: MagicMock,
) -> None:
    # Fail twice, then succeed
    mock_httpx_client.post.side_effect = [
        httpx.NetworkError("Failed to connect"),
        httpx.HTTPStatusError(
            "Server Error",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        ),
        MagicMock(status_code=200),
    ]

    # Mock time.sleep to speed up tests
    with patch("time.sleep"):
        gert_client.mark_complete()

    assert mock_httpx_client.post.call_count == 3
    # Check it called the right endpoint all three times
    for call in mock_httpx_client.post.call_args_list:
        assert "/realizations/42/complete" in call[0][0]


def test_retry_logic_permanent_failure(
    gert_client: GertForwardModelClient,
    mock_httpx_client: MagicMock,
) -> None:
    mock_httpx_client.post.side_effect = httpx.NetworkError("Persistent Failure")

    with patch("time.sleep"), pytest.raises(httpx.NetworkError):
        gert_client.mark_complete()

    assert mock_httpx_client.post.call_count == 5
