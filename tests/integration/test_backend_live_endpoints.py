import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect

from gert.__main__ import _scan_for_configs
from gert.server.gert_server import create_gert_server

app = create_gert_server()


def test_logs_stream_endpoint(client: TestClient) -> None:
    """Verify that the SSE logs stream endpoint returns a 200 OK and valid event stream."""
    with client.stream("GET", "/api/logs/stream") as response:
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

        # Read just the first chunk to verify it's working
        lines = []
        for line in response.iter_lines():
            if line:
                lines.append(line)
            if len(lines) >= 1:
                break

        # Note: If logs/gert.log is empty, it might yield 'data: Log file not found'
        assert len(lines) > 0
        assert lines[0].startswith("data: ")


def test_websocket_pulse_endpoint(simple_example_dir: Path, client: TestClient) -> None:
    """Verify that the execution events WebSocket correctly accepts connections."""
    # Use the path from the fixture, not a hardcoded relative path
    configs = _scan_for_configs([simple_example_dir])

    # This will now succeed because the path is correct and files are found
    exp_id, config = next(iter(configs.items()))

    # The `client` is now injected by the fixture, ensuring a clean app state.
    # The `with TestClient(app) as client:` block is no longer needed.

    # Register
    client.post(
        "/api/experiments",
        params={"id": exp_id},
        content=config.model_dump_json(),
        headers={"Content-Type": "application/json"},
    )
    # Start
    res = client.post(f"/api/experiments/{exp_id}/start")
    exec_id = res.json()["execution_id"]

    # Test WS
    try:
        with client.websocket_connect(
            f"/api/experiments/{exp_id}/executions/{exec_id}/events",
        ) as websocket:
            # This will now receive the message because the background task
            # can start correctly in the clean application environment.
            data = websocket.receive_text()
            parsed = json.loads(data)
            assert isinstance(parsed, list)
    except WebSocketDisconnect:
        pytest.fail("WebSocket disconnected unexpectedly")
