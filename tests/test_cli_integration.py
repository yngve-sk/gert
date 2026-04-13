# ruff: noqa: S404, S603, PLW1510
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from gert.discovery import wait_for_gert_server


def get_free_port() -> int:
    """Get a random free port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return int(s.getsockname()[1])


def test_implicit_server_start(
    monkeypatch: pytest.MonkeyPatch,
    simple_example_dir: Path,
    tmp_path: Path,
) -> None:
    """Test that running an experiment without a server implicitly starts one."""
    config_path = simple_example_dir / "experiment.json"
    monkeypatch.setenv("GERT_DISCOVERY_DIR", str(tmp_path))
    # No need to modify config with --api-url anymore
    # The discovery mechanism handles this automatically

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "gert",
            "run",
            str(config_path),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0
    assert "Starting temporary server" in result.stdout
    assert "Iteration 0 completed" in result.stdout


def test_explicit_server_start(
    monkeypatch: pytest.MonkeyPatch,
    simple_example_dir: Path,
    tmp_path: Path,
) -> None:
    """Test running an experiment against an explicitly started server using service discovery."""
    config_path = simple_example_dir / "experiment.json"
    discovery_dir = tmp_path / "gert_discovery"
    discovery_dir.mkdir()

    monkeypatch.setenv("GERT_DISCOVERY_DIR", str(discovery_dir))

    # Start the server without a specific port. It will find a free port and
    # advertise itself in the discovery directory.
    server_process = subprocess.Popen(
        [sys.executable, "-m", "gert", "server"],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        # Wait for the server to be ready using the discovery mechanism.
        wait_for_gert_server(timeout=15)

        # Run the experiment without the --api-url. The 'gert run' command will
        # automatically find the server via the discovery file.
        result = subprocess.run(
            [sys.executable, "-m", "gert", "run", str(config_path), "--wait"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )

        # Verify that 'gert run' used the existing server and did not start its own.
        assert "Starting temporary server" not in result.stdout
        assert "Iteration 0 completed" in result.stdout

    finally:
        server_process.terminate()
        server_process.wait(timeout=5)
        # For debugging in case of failure
        if sys.exc_info()[0] and server_process.stdout and server_process.stderr:
            print("\n--- Server STDOUT ---\n", server_process.stdout.read())
            print("\n--- Server STDERR ---\n", server_process.stderr.read())


@pytest.mark.timeout(45)
def test_explicit_server_multiple_experiments(
    simple_example_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that a single explicitly started server can run multiple experiments via service discovery."""
    config_path = simple_example_dir / "experiment.json"
    discovery_dir = tmp_path / "gert_discovery"
    discovery_dir.mkdir()

    # Use monkeypatch to ensure the server and all clients use a temporary
    # discovery file for test isolation.
    monkeypatch.setenv("GERT_DISCOVERY_DIR", str(discovery_dir))

    # Start the server. It will find a free port and advertise itself via the
    # discovery file in GERT_DISCOVERY_DIR.
    server_process = subprocess.Popen(
        [sys.executable, "-m", "gert", "server"],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        # Wait for the server to be fully ready using the discovery mechanism.
        # This confirms the server started, wrote the file, and is responsive.
        wait_for_gert_server(timeout=15)

        # Run first experiment.
        # We do NOT pass --api-url. The 'gert run' command and the subsequent
        # forward model it spawns will use the discovery file to find the server.
        res1 = subprocess.run(
            [
                sys.executable,
                "-m",
                "gert",
                "run",
                str(config_path),
                "--wait",
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert res1.returncode == 0
        assert "Iteration 0 completed" in res1.stdout

        # Run second experiment, also using discovery.
        res2 = subprocess.run(
            [
                sys.executable,
                "-m",
                "gert",
                "run",
                str(config_path),
                "--wait",
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert res2.returncode == 0
        assert "Iteration 0 completed" in res2.stdout

    finally:
        server_process.terminate()
        server_process.wait(timeout=5)
        # For debugging in case of failure
        if sys.exc_info()[0] and server_process.stdout and server_process.stderr:
            print("\n--- Server STDOUT ---\n", server_process.stdout.read())
            print("\n--- Server STDERR ---\n", server_process.stderr.read())


def test_implicit_server_isolation(
    monkeypatch: pytest.MonkeyPatch,
    simple_example_dir: Path,
    tmp_path: Path,
) -> None:
    """
    Test that 'gert run' starts a discoverable server that is cleaned up afterward.
    1. Starts 'gert run' in the background, which creates a temporary server.
    2. Confirms that a separate 'gert connect' process can find and connect to it.
    3. Waits for the run to complete.
    4. Confirms the temporary server has been shut down and is no longer discoverable.
    """
    config_path = simple_example_dir / "experiment.json"
    discovery_dir = tmp_path / "gert_discovery"
    discovery_dir.mkdir()

    monkeypatch.setenv("GERT_DISCOVERY_DIR", str(discovery_dir))

    # 1. Start 'gert run' as a background process.
    # It will start a temporary server, begin the experiment, and then wait
    # for the experiment to finish.
    run_process = subprocess.Popen(
        [sys.executable, "-m", "gert", "run", str(config_path), "--wait"],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        # Wait for the temporary server to be fully ready.
        conn_info = wait_for_gert_server(timeout=15)
        assert (discovery_dir / "server_info.json").exists()

        # 2. While the server is running, confirm a separate process can connect.
        connect_result = subprocess.run(
            [sys.executable, "-m", "gert", "connection", "info"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        assert "Found running GERT server" in connect_result.stdout
        assert conn_info.base_url in connect_result.stdout

        # 3. Wait for the background 'gert run' process to complete.
        stdout, stderr = run_process.communicate(timeout=30)
        assert run_process.returncode == 0, (
            f"gert run failed:\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
        )
        assert "Starting temporary server" in stdout
        assert "Iteration 0 completed" in stdout
        assert "Shutting down temporary server" in stdout

    finally:
        # Ensure the background process is terminated if the test fails
        if run_process.poll() is None:
            run_process.terminate()
            run_process.wait(5)

    # 4. Confirm the server was cleaned up and is no longer discoverable.
    post_run_connect_result = subprocess.run(
        [sys.executable, "-m", "gert", "connection", "info"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert post_run_connect_result.returncode != 0
    assert "No running GERT server found" in post_run_connect_result.stderr
