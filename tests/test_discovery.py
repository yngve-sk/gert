import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import psutil
import pytest
import uvicorn

from gert.discovery import (
    NoGertServerFoundError,
    find_gert_server,
    get_discovery_file,
    wait_for_gert_server,
)
from gert.server.gert_server import create_gert_server, get_free_port
from gert.server.models import ConnectionInfo

SERVER_INFO: dict[str, Any] = {
    "host": "127.0.0.1",
    "port": 8001,
    "base_url": "http://127.0.0.1:8001",
    "token": "test_token",
    "server_id": "test_server_123",
    "pid": 12345,
    "version": "0.1.0",
}


@pytest.fixture(autouse=True)
def setup_discovery_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure a clean discovery directory for each test."""
    monkeypatch.setenv("GERT_DISCOVERY_DIR", str(tmp_path))


@patch("gert.discovery.psutil.Process")
@patch("gert.discovery.httpx.Client")
def test_find_gert_server_success(
    mock_httpx_client: MagicMock,
    mock_process: MagicMock,
) -> None:
    """Test successful server discovery."""
    # Setup mocks
    mock_proc_instance = mock_process.return_value
    mock_proc_instance.is_running.return_value = True
    mock_proc_instance.name.return_value = "python"

    mock_http_instance = mock_httpx_client.return_value.__enter__.return_value
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = SERVER_INFO
    mock_http_instance.get.return_value = mock_response

    # Create discovery file
    get_discovery_file().parent.mkdir(exist_ok=True)
    get_discovery_file().write_text(json.dumps(SERVER_INFO))

    info = find_gert_server()

    assert info.model_dump() == SERVER_INFO
    mock_http_instance.get.assert_called_once_with("/connection-info")


def test_find_gert_server_no_file() -> None:
    """Test discovery when the discovery file does not exist."""
    with pytest.raises(
        NoGertServerFoundError,
        match=r"No GERT server discovery file found.",
    ):
        find_gert_server()


@patch("gert.discovery.psutil.Process")
def test_find_gert_server_stale_file_process_not_running(
    mock_process: MagicMock,
) -> None:
    """Test discovery when the process in the file is not running."""
    mock_process.side_effect = psutil.NoSuchProcess(pid=SERVER_INFO["pid"])
    get_discovery_file().parent.mkdir(exist_ok=True)
    get_discovery_file().write_text(json.dumps(SERVER_INFO))

    with pytest.raises(NoGertServerFoundError, match="Stale discovery file"):
        find_gert_server()
    assert not get_discovery_file().exists()


@patch("gert.discovery.psutil.Process")
@patch("gert.discovery.httpx.Client")
def test_find_gert_server_stale_file_not_responsive(
    mock_httpx_client: MagicMock,
    mock_process: MagicMock,
) -> None:
    """Test discovery when the server is not responsive."""
    mock_proc_instance = mock_process.return_value
    mock_proc_instance.is_running.return_value = True
    mock_proc_instance.name.return_value = "python"
    mock_http_instance = mock_httpx_client.return_value.__enter__.return_value
    mock_http_instance.get.side_effect = httpx.ConnectError("Connection failed")
    get_discovery_file().parent.mkdir(exist_ok=True)
    get_discovery_file().write_text(json.dumps(SERVER_INFO))

    with pytest.raises(NoGertServerFoundError, match="not responsive"):
        find_gert_server()
    assert (
        get_discovery_file().exists()
    )  # File should NOT be deleted on connection error


def run_server(host: str = "127.0.0.1") -> None:
    """Target function to run the uvicorn server."""
    port = get_free_port()
    pid = os.getpid()
    connection_info = ConnectionInfo(
        host=host,
        port=port,
        base_url=f"http://{host}:{port}",
        token=f"gert_{secrets.token_hex(16)}",
        server_id=f"gert_{pid}_{int(time.time())}",
        pid=pid,
    )

    try:
        discovery_file = get_discovery_file()
        discovery_file.parent.mkdir(parents=True, exist_ok=True)
        with get_discovery_file().open("w", encoding="utf-8") as f:
            f.write(connection_info.model_dump_json(indent=2))

        app = create_gert_server(conn_info=connection_info)
        uvicorn.run(app, host=host, port=port, log_level="error")
    finally:
        if get_discovery_file().exists():
            get_discovery_file().unlink()


def test_wait_for_gert_server_integration() -> None:
    """Test waiting for a real server process to start and be discovered."""
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    try:
        connection_info_discovered = wait_for_gert_server(timeout=30)
        assert hasattr(connection_info_discovered, "base_url")
        assert connection_info_discovered.port > 0
        assert get_discovery_file().exists()
    finally:
        # The server runs as a daemon thread, so it will be terminated
        # automatically when the main thread (the test) exits.
        # We still need to make sure the discovery file is cleaned up if the
        # server's finally block doesn't get to run in time.
        if get_discovery_file().exists():
            get_discovery_file().unlink(missing_ok=True)
        # Give a moment for the server thread to shut down
        time.sleep(0.1)


@patch("gert.discovery.psutil.Process")
def test_find_gert_server_stale_file_abrupt_shutdown(
    mock_process: MagicMock,
) -> None:
    """Test discovery after an abrupt server process shutdown (no graceful cleanup)."""
    # Simulate a server that wrote the file, but then crashed
    mock_process.side_effect = psutil.NoSuchProcess(pid=SERVER_INFO["pid"])

    get_discovery_file().parent.mkdir(exist_ok=True)
    get_discovery_file().write_text(json.dumps(SERVER_INFO))

    with pytest.raises(NoGertServerFoundError, match="Stale discovery file"):
        find_gert_server()
    assert not get_discovery_file().exists()
