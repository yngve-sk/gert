# ruff: noqa: S404, S603, PLW1510
import json
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest


@pytest.fixture
def simple_example_dir(tmp_path: Path) -> Path:
    """Fixture to copy the simple example into a temporary directory."""
    example_src = Path("examples/simple")
    dest = tmp_path / "simple"
    shutil.copytree(example_src, dest)
    return dest


def get_free_port() -> int:
    """Get a random free port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return int(s.getsockname()[1])


def test_implicit_server_start(simple_example_dir: Path, tmp_path: Path) -> None:
    """Test that running an experiment without a server implicitly starts one."""
    port = get_free_port()
    config_path = simple_example_dir / "experiment.json"
    api_url = f"http://127.0.0.1:{port}"

    # Update experiment.json with the dynamic api-url
    with config_path.open() as f:
        config = json.load(f)
    config["forward_model_steps"][0]["args"].extend(["--api-url", api_url])
    with config_path.open("w") as f:
        json.dump(config, f)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "gert",
            "run",
            str(config_path),
            "--api-url",
            api_url,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0
    assert "Starting temporary server" in result.stdout
    assert "All realizations completed" in result.stdout


def test_explicit_server_start(simple_example_dir: Path, tmp_path: Path) -> None:
    """Test running an experiment against an explicitly started server."""
    port = get_free_port()
    config_path = simple_example_dir / "experiment.json"
    api_url = f"http://127.0.0.1:{port}"

    # Update experiment.json with the dynamic api-url
    with config_path.open() as f:
        config = json.load(f)
    config["forward_model_steps"][0]["args"].extend(["--api-url", api_url])
    with config_path.open("w") as f:
        json.dump(config, f)

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
                pass
        else:
            pytest.fail("Server did not start in time")

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "gert",
                "run",
                str(config_path),
                "--api-url",
                api_url,
                "--wait",
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 0
        assert "Starting temporary server" not in result.stdout
        assert "All realizations completed" in result.stdout

    finally:
        server_process.terminate()
        server_process.wait(timeout=5)


def test_explicit_server_multiple_experiments(
    simple_example_dir: Path,
    tmp_path: Path,
) -> None:
    """Test that a single explicitly started server can run multiple experiments."""
    port = get_free_port()
    config_path = simple_example_dir / "experiment.json"
    api_url = f"http://127.0.0.1:{port}"

    # Update experiment.json with the dynamic api-url
    with config_path.open() as f:
        config = json.load(f)
    config["forward_model_steps"][0]["args"].extend(["--api-url", api_url])
    with config_path.open("w") as f:
        json.dump(config, f)

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
                pass
        else:
            pytest.fail("Server did not start in time")

        # Run first experiment
        res1 = subprocess.run(
            [
                sys.executable,
                "-m",
                "gert",
                "run",
                str(config_path),
                "--api-url",
                api_url,
                "--wait",
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert res1.returncode == 0
        assert "All realizations completed" in res1.stdout

        # Run second experiment
        res2 = subprocess.run(
            [
                sys.executable,
                "-m",
                "gert",
                "run",
                str(config_path),
                "--api-url",
                api_url,
                "--wait",
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert res2.returncode == 0
        assert "All realizations completed" in res2.stdout

    finally:
        server_process.terminate()
        server_process.wait(timeout=5)


def test_implicit_server_isolation(simple_example_dir: Path, tmp_path: Path) -> None:
    """Test that an implicitly started server shuts down after the run completes."""
    port = get_free_port()
    config_path = simple_example_dir / "experiment.json"
    api_url = f"http://127.0.0.1:{port}"

    # Update experiment.json with the dynamic api-url
    with config_path.open() as f:
        config = json.load(f)
    config["forward_model_steps"][0]["args"].extend(["--api-url", api_url])
    with config_path.open("w") as f:
        json.dump(config, f)

    # Run first experiment (implicit server)
    res1 = subprocess.run(
        [
            sys.executable,
            "-m",
            "gert",
            "run",
            str(config_path),
            "--api-url",
            api_url,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert res1.returncode == 0
    assert "Starting temporary server" in res1.stdout

    # The server should now be dead.
    # If we try to hit the API, it should fail.
    with pytest.raises(httpx.ConnectError):
        httpx.get(f"{api_url}/docs")
