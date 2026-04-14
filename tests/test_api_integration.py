# ruff: noqa: S404, S603, ASYNC220, ASYNC210, ASYNC251
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest


def get_free_port() -> int:
    """Get a random free port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return int(s.getsockname()[1])


@pytest.mark.asyncio
async def test_api_connect_pause_resume_flow(tmp_path: Path) -> None:
    """Test that a client can connect, view state, pause, and resume an experiment via API."""
    port = get_free_port()
    api_url = f"http://127.0.0.1:{port}/api"

    server_process = subprocess.Popen(
        [sys.executable, "-m", "gert", "server", "--port", str(port)],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        # Wait for server to be ready
        end_time = time.monotonic() + 10
        while time.monotonic() < end_time:
            try:
                httpx.get(f"{api_url}/docs")
                break
            except httpx.ConnectError:
                time.sleep(0.1)
        else:
            pytest.fail("Server did not start in time")

        # Create a tiny robust sleep script
        dummy_script = tmp_path / "dummy_sleep.sh"
        dummy_script.write_text("#!/bin/bash\nsleep $1\n")
        dummy_script.chmod(0o755)

        # 1. Register Experiment
        config = {
            "name": "api_test_exp",
            "base_working_directory": str(tmp_path),
            "storage_base": str(tmp_path / "permanent_storage"),
            "realization_workdirs_base": str(tmp_path / "workdirs"),
            "forward_model_steps": [
                {
                    "name": "sleepy",
                    "executable": str(dummy_script),
                    "args": ["10"],
                },
            ],
            "parameter_matrix": {"values": {"p1": {"0": 1.0, "1": 2.0}}},
            "queue_config": {"backend": "local"},
            "observations": [],
            "updates": [],
        }

        res = httpx.post(f"{api_url}/experiments", json=config)
        assert res.status_code == 201, f"Failed to register config: {res.text}"

        # 2. Start Execution
        res = httpx.post(f"{api_url}/experiments/api_test_exp/start")
        assert res.status_code == 200, f"Failed to start execution: {res.text}"
        exec_id = res.json()["execution_id"]

        # 3. Connect: View State (Should be RUNNING)
        time.sleep(1.5)  # Give orchestrator a tiny bit of time to start up
        res = httpx.get(
            f"{api_url}/experiments/api_test_exp/executions/{exec_id}/state",
        )
        assert res.status_code == 200
        state = res.json()
        assert state["status"] == "RUNNING"

        # Connect: View Realization Statuses
        res = httpx.get(
            f"{api_url}/experiments/api_test_exp/executions/{exec_id}/status",
        )
        assert res.status_code == 200
        statuses = res.json()
        assert len(statuses) > 0, "Should have started pending/active realizations"

        # 4. Pause Execution (Force)
        res = httpx.post(
            f"{api_url}/experiments/api_test_exp/executions/{exec_id}/pause?force=true",
        )
        assert res.status_code == 200

        # Wait for cancellation to settle
        time.sleep(1.5)

        res = httpx.get(
            f"{api_url}/experiments/api_test_exp/executions/{exec_id}/state",
        )
        assert res.status_code == 200
        assert res.json()["status"] == "PAUSED", (
            "Execution did not transition to PAUSED"
        )

        # 5. Resume Execution
        res = httpx.post(
            f"{api_url}/experiments/api_test_exp/executions/{exec_id}/resume",
        )
        assert res.status_code == 200

        time.sleep(0.5)
        res = httpx.get(
            f"{api_url}/experiments/api_test_exp/executions/{exec_id}/state",
        )
        assert res.status_code == 200
        assert res.json()["status"] == "RUNNING", (
            "Execution did not transition back to RUNNING"
        )

        # Clean up: force pause again so it exits cleanly
        httpx.post(
            f"{api_url}/experiments/api_test_exp/executions/{exec_id}/pause?force=true",
        )

    finally:
        server_process.terminate()
        server_process.wait(timeout=5)
