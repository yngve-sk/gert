# ruff: noqa: S404, S603
import io
import json
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Generator
from pathlib import Path

import httpx
import numpy as np
import polars as pl
import pytest


def get_free_port() -> int:
    """Get a random free port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return int(s.getsockname()[1])


@pytest.fixture(autouse=True)
def cleanup_storage() -> Generator[None]:
    """Ensure a clean storage directory for the test."""
    storage_path = Path("./permanent_storage")
    workdirs_path = Path("./workdirs")
    if storage_path.exists():
        shutil.rmtree(storage_path)
    if workdirs_path.exists():
        shutil.rmtree(workdirs_path)
    yield
    if storage_path.exists():
        shutil.rmtree(storage_path)
    if workdirs_path.exists():
        shutil.rmtree(workdirs_path)


def test_semi_realistic_da_convergence(
    copy_example: Callable[[str], Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Run semi_realistic example and verify that variance decreases over iterations."""
    config_dir = copy_example("semi_realistic")
    monkeypatch.chdir(config_dir)

    subprocess.run([sys.executable, "generate_prior.py"], check=True)
    subprocess.run([sys.executable, "setup_observations.py"], check=True)

    with Path("experiment.json").open(encoding="utf-8") as f:
        config_data = json.load(f)

    port = get_free_port()
    api_url = f"http://127.0.0.1:{port}"

    # Update config to include the dynamic API URL for all field models
    for step in config_data["forward_model_steps"]:
        step["args"].extend(["--api-url", api_url])

    server_process = subprocess.Popen(
        [sys.executable, "-m", "gert", "server", "--port", str(port)],
        cwd=config_dir,
        stdout=sys.stdout,
        stderr=sys.stderr,
        text=True,
    )
    try:
        # Wait for server to be ready
        end_time = time.monotonic() + 10
        client = httpx.Client(base_url=api_url, timeout=120.0)
        while time.monotonic() < end_time:
            try:
                client.get("/docs")
                break
            except httpx.ConnectError:
                pass
        else:
            pytest.fail("Server did not start in time")

        # 2. Register and start experiment
        resp = client.post("/experiments", json=config_data)
        assert resp.status_code == 201
        experiment_id = resp.json()["id"]

        resp = client.post(f"/experiments/{experiment_id}/start")
        assert resp.status_code == 200
        execution_id = resp.json()["execution_id"]

        # 3. Poll for completion
        max_wait = 300  # seconds
        start_time = time.time()

        num_iterations = len(config_data["updates"]) + 1
        expected_realizations = 20

        completed = False
        statuses = []
        while time.time() - start_time < max_wait:
            state_resp = client.get(
                f"/experiments/{experiment_id}/executions/{execution_id}/state",
            )
            state_resp.raise_for_status()
            exec_state = state_resp.json()
            if exec_state["status"] == "FAILED":
                server_process.terminate()
                server_process.wait(timeout=5)
                pytest.fail(f"Background execution failed: {exec_state.get('error')}")

            resp = client.get(
                f"/experiments/{experiment_id}/executions/{execution_id}/status",
            )
            assert resp.status_code == 200
            statuses = resp.json()

            done_count = sum(
                1 for s in statuses if s["status"] in {"COMPLETED", "FAILED"}
            )

            if done_count == num_iterations * expected_realizations:
                completed = True
                break
            time.sleep(1)

        if not completed:
            server_process.terminate()
            server_process.wait(timeout=5)
            pytest.fail(
                f"Experiment did not complete in {max_wait}s. Statuses: {statuses}",
            )

        # Check for FAILED states
        failed_count = sum(1 for s in statuses if s["status"] == "FAILED")
        assert failed_count == 0, (
            f"Found {failed_count} failed jobs! Statuses: {statuses}"
        )

        # 4. Analyze variance of PERM parameter over iterations
        variances = []

        for it in range(num_iterations):
            params_resp = client.get(
                f"/experiments/{experiment_id}/executions/{execution_id}/ensembles/{it}/parameters",
            )
            assert params_resp.status_code == 200
            df = pl.read_parquet(io.BytesIO(params_resp.content))

            # PERM is a list column. Convert to 2D array: (realizations, cells)
            perms_2d = np.array(df["PERM"].to_list())

            # Calculate variance across realizations (axis=0) for each cell, then average
            cell_variances = np.var(perms_2d, axis=0)
            ensemble_spread = float(np.mean(cell_variances))

            variances.append(ensemble_spread)
        # 5. Assert lessening of variance
        for i in range(1, num_iterations):
            assert variances[i] < variances[i - 1], (
                f"Ensemble spread did not decrease at iteration {i}: "
                f"{variances[i]} >= {variances[i - 1]}"
            )
    finally:
        client.close()
        server_process.kill()
        server_process.wait(timeout=5)
