# ruff: noqa: S404, S603
import io
import json
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import httpx
import numpy as np
import polars as pl
import pytest

from gert.discovery import wait_for_gert_server


def test_semi_realistic_da_convergence(
    copy_example: Callable[[str], Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Run semi_realistic example and verify that variance decreases over iterations."""
    config_dir = copy_example("semi_realistic")
    monkeypatch.chdir(config_dir)

    monkeypatch.setenv("GERT_DISCOVERY_DIR", str(tmp_path))

    subprocess.run([sys.executable, "generate_prior.py"], check=True)
    subprocess.run([sys.executable, "setup_observations.py"], check=True)

    with Path("experiment.json").open(encoding="utf-8") as f:
        config_data = json.load(f)

    # Start server using discovery (no manual port specification)
    server_process = subprocess.Popen(
        [sys.executable, "-m", "gert", "server"],  # Remove --port 0
        cwd=config_dir,
        stdout=sys.stdout,
        stderr=sys.stderr,
        text=True,
    )

    client = httpx.Client(timeout=120.0)
    try:
        # Wait for server to be ready and discover connection info
        connection_info = wait_for_gert_server(timeout=30)
        api_url = connection_info.base_url
        client.base_url = api_url

        # 2. Register and start experiment
        resp = client.post("/api/experiments", json=config_data)
        assert resp.status_code == 201
        experiment_id = resp.json()["id"]

        resp = client.post(f"/api/experiments/{experiment_id}/start")
        assert resp.status_code == 200
        execution_id = resp.json()["execution_id"]

        # 3. Poll for completion
        max_wait = 300  # seconds
        start_time = time.time()

        num_iterations = len(config_data["updates"]) + 1
        expected_realizations = 20

        completed = False
        while time.time() - start_time < max_wait:
            state_resp = client.get(
                f"/api/experiments/{experiment_id}/executions/{execution_id}/state",
            )
            state_resp.raise_for_status()
            exec_state = state_resp.json()
            if exec_state["status"] == "FAILED":
                server_process.terminate()
                server_process.wait(timeout=5)
                pytest.fail(f"Background execution failed: {exec_state.get('error')}")
            if exec_state["status"] == "COMPLETED":
                completed = True
                break

            time.sleep(1)

        if not completed:
            server_process.terminate()
            server_process.wait(timeout=5)
            pytest.fail(f"Experiment did not complete in {max_wait}s.")

        resp = client.get(
            f"/api/experiments/{experiment_id}/executions/{execution_id}/status",
        )
        assert resp.status_code == 200
        statuses = resp.json()

        done_count = sum(
            1
            for s in statuses
            if s["status"] in {"COMPLETED", "FAILED"} and s["iteration"] >= 0
        )
        if done_count != num_iterations * expected_realizations:
            pytest.fail(
                f"Expected {num_iterations * expected_realizations} done jobs, got {done_count}. Statuses: {statuses}",
            )

        # Check for FAILED states
        failed_count = sum(
            1 for s in statuses if s["status"] == "FAILED" and s["iteration"] >= 0
        )
        assert failed_count == 0, (
            f"Found {failed_count} failed jobs! Statuses: {statuses}"
        )

        # 4. Analyze variance of PERM parameter over iterations
        variances = []

        for it in range(num_iterations):
            params_resp = client.get(
                f"/api/experiments/{experiment_id}/executions/{execution_id}/ensembles/{it}/parameters",
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
