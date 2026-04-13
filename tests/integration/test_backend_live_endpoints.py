import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect

from gert.__main__ import _scan_for_configs
from gert.server.gert_server import create_gert_server

app = create_gert_server()


def test_logs_stream_endpoint() -> None:
    """Verify that the SSE logs stream endpoint returns a 200 OK and valid event stream."""
    configs = _scan_for_configs([Path("examples/simple")])
    exp_id, _ = next(iter(configs.items()))

    with TestClient(app) as client:
        res = client.post("/experiments", json=configs[exp_id].model_dump())
        assert res.status_code == 201

        start_res = client.post(f"/experiments/{exp_id}/start")
        exec_id = start_res.json()["execution_id"]

        with client.stream(
            "GET",
            f"/experiments/{exp_id}/executions/{exec_id}/logs/stream",
        ) as response:
            assert response.status_code == 200
            assert (
                response.headers["content-type"] == "text/event-stream; charset=utf-8"
            )

            # Read just the first chunk to verify it's working
            lines = []
            for line in response.iter_lines():
                if line:
                    lines.append(line)
                if len(lines) >= 1:
                    break

            assert len(lines) > 0
            assert lines[0].startswith("data: ")


def test_websocket_pulse_endpoint() -> None:
    """Verify that the execution events WebSocket correctly accepts connections."""
    configs = _scan_for_configs([Path("examples/simple")])
    exp_id, config = next(iter(configs.items()))

    with TestClient(app) as client:
        # Register
        client.post(
            "/experiments",
            params={"id": exp_id},
            content=config.model_dump_json(),
            headers={"Content-Type": "application/json"},
        )
        # Start
        res = client.post(f"/experiments/{exp_id}/start")
        exec_id = res.json()["execution_id"]

        # Test WS
        try:
            with client.websocket_connect(
                f"/experiments/{exp_id}/executions/{exec_id}/events",
            ) as websocket:
                data = websocket.receive_text()
                parsed = json.loads(data)
                assert isinstance(parsed, list)
        except WebSocketDisconnect:
            pytest.fail("WebSocket disconnected unexpectedly")
