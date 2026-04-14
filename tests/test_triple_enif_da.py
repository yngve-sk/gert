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
from gert.experiments import ExperimentConfig


def test_triple_enif_da_convergence(
    copy_example: Callable[[str], Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Run triple_enif example and verify that variance decreases over iterations."""
    # --- 1. SETUP ---
    # Prepare the experiment directory, pre-run scripts, and configuration
    config_dir = copy_example("triple_enif")
    monkeypatch.chdir(config_dir)
    monkeypatch.setenv("GERT_DISCOVERY_DIR", str(tmp_path))

    if Path("generate_prior.py").exists():
        subprocess.run([sys.executable, "generate_prior.py"], check=True)
    if Path("setup_observations.py").exists():
        subprocess.run([sys.executable, "setup_observations.py"], check=True)

    with Path("experiment.json").open(encoding="utf-8") as f:
        config_data = json.load(f) | {
            "base_working_directory": str(config_dir.absolute()),
        }
    config = ExperimentConfig.model_validate(config_data)
    num_iterations = len(config.updates) + 1

    # --- 2. EXECUTE ---
    # Start the GERT server as a background process
    server_process = subprocess.Popen(
        [sys.executable, "-m", "gert", "server"],
        cwd=config_dir,
        text=True,
    )
    with server_process:
        try:
            connection_info = wait_for_gert_server(timeout=30)
            with httpx.Client(
                base_url=connection_info.base_url,
                timeout=120.0,
            ) as client:
                # Register and start the experiment
                resp = client.post("/api/experiments", json=config_data)
                resp.raise_for_status()
                experiment_id = resp.json()["id"]

                resp = client.post(f"/api/experiments/{experiment_id}/start")
                resp.raise_for_status()
                execution_id = resp.json()["execution_id"]

                # --- 3. POLL FOR COMPLETION ---
                start_time = time.time()
                while time.time() - start_time < 300:  # 5-minute timeout
                    state_resp = client.get(
                        f"/api/experiments/{experiment_id}/executions/{execution_id}/state",
                    )
                    state_resp.raise_for_status()
                    exec_state = state_resp.json()

                    if exec_state["status"] == "COMPLETED":
                        break
                    if exec_state["status"] == "FAILED":
                        pytest.fail(f"Execution failed: {exec_state.get('error')}")
                    time.sleep(2)
                else:
                    pytest.fail("Experiment did not complete within the time limit.")

                # --- 4. ANALYZE RESULTS ---
                # Fetch the parameter variance for each iteration
                variances = []
                for it in range(num_iterations):
                    params_resp = client.get(
                        f"/api/experiments/{experiment_id}/executions/{execution_id}/ensembles/{it}/parameters",
                    )
                    params_resp.raise_for_status()
                    df = pl.read_parquet(io.BytesIO(params_resp.content))
                    perms_2d = np.array(df["MULTFLT"].to_list())
                    ensemble_spread = float(np.mean(np.var(perms_2d, axis=0)))
                    variances.append(ensemble_spread)

                # Assert that the variance (ensemble spread) decreases at each step
                for i in range(1, num_iterations):
                    assert variances[i] < variances[i - 1], (
                        f"Ensemble spread should decrease at iteration {i}. "
                        f"Got: {variances[i]}, expected less than {variances[i - 1]}."
                    )
        finally:
            # Ensure the server is terminated
            server_process.kill()
            server_process.wait(timeout=5)
