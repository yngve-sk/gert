# ruff: noqa: S404, S603
import os
import shutil
import subprocess
import sys
from pathlib import Path

import httpx

from gert.discovery import wait_for_gert_server


def test_ui_smoke(use_tmpdir: Path) -> None:
    """
    Smoke test to ensure 'gert ui' starts without crashing and serves the root HTML successfully.
    """
    tmp_dir = Path("./repro_ui").resolve()
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir()

    discovery_dir = tmp_dir / "discovery"
    discovery_dir.mkdir()

    env = os.environ.copy()
    env["GERT_DISCOVERY_DIR"] = str(discovery_dir)
    env["PYTHONPATH"] = str(Path("src").resolve()) + ":" + env.get("PYTHONPATH", "")
    # Prevent webbrowser from actually opening a window during test
    env["BROWSER"] = "none"

    print("Starting 'gert ui examples/'...")

    server_proc = subprocess.Popen(
        [sys.executable, "-m", "gert", "ui", str(Path("examples").resolve())],
        cwd=tmp_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        # Wait for server to become available
        print("Waiting for server to become available...")
        os.environ["GERT_DISCOVERY_DIR"] = str(discovery_dir)
        server_info = wait_for_gert_server(timeout=10)
        print(f"Server found at {server_info.base_url}")

        # Test 1: Fetch the root to ensure the Svelte SPA is being served
        client = httpx.Client(base_url=server_info.base_url)
        resp = client.get("/")
        print(f"GET / response: {resp.status_code}")

        assert resp.status_code == 200, f"Expected 200 OK, got {resp.status_code}"
        assert "<!doctype html>" in resp.text.lower(), (
            "Response does not look like HTML"
        )

        # Test 2: Try fetching experiments list (API)
        api_resp = client.get("/api/experiments")
        print(f"GET /experiments response: {api_resp.status_code}")
        assert api_resp.status_code == 200, (
            f"Expected API 200, got {api_resp.status_code}"
        )

        print("✅ UI Smoke test passed.")

    finally:
        server_proc.terminate()
        try:
            outs, errs = server_proc.communicate(timeout=2)
            if server_proc.returncode not in {0, -15}:  # SIGTERM
                print(f"Server exited with {server_proc.returncode}")
                print(f"STDOUT:\n{outs}")
                print(f"STDERR:\n{errs}")
        except subprocess.TimeoutExpired:
            server_proc.kill()
        shutil.rmtree(tmp_dir)
