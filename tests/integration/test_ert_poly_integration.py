# ruff: noqa: S404, S603
import asyncio
import json
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any

import httpx
import pytest


def get_free_port() -> int:
    """Get a random free port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def server_factory(
    tmp_path: Path,
) -> Generator[Callable[[int, Path], tuple[subprocess.Popen[Any], Path]]]:
    """Fixture to start a GERT server for integration tests.

    Yields:
        A function to start the server.
    """
    processes: list[tuple[subprocess.Popen[Any], Any, Path]] = []

    def _start_server(port: int, cwd: Path) -> tuple[subprocess.Popen[Any], Path]:
        server_log = cwd / f"server_{port}.log"
        with Path(server_log).open("w", encoding="utf-8") as log_f:
            p = subprocess.Popen(
                [sys.executable, "-m", "gert", "server", "--port", str(port)],
                cwd=cwd,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                text=True,
            )
            processes.append((p, log_f, server_log))
            return p, server_log

    yield _start_server

    for p, _, _ in processes:
        p.terminate()
        p.wait(timeout=5)


async def wait_for_server(api_url: str) -> None:
    """Wait for server to be ready."""
    timeout = 10.0
    end_time = time.monotonic() + timeout
    while time.monotonic() < end_time:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{api_url}/health")
                if response.status_code == 200:
                    return
        except (httpx.ConnectError, httpx.HTTPError):
            await asyncio.sleep(0.1)
    pytest.fail(f"Server at {api_url} did not start in time")


@pytest.mark.asyncio
async def test_ert_poly_full_run(
    tmp_path: Path,
    server_factory: Callable[[int, Path], tuple[subprocess.Popen[Any], Path]],
) -> None:
    """Test the full ert_poly example run."""
    port = get_free_port()
    api_url = f"http://127.0.0.1:{port}"

    example_dir = Path("examples/ert_poly")
    shutil.copytree(example_dir, tmp_path, dirs_exist_ok=True)

    server_factory(port, tmp_path)
    await wait_for_server(api_url)

    # 1. Register
    config_path = tmp_path / "experiment.json"
    config_data = json.loads(config_path.read_text(encoding="utf-8"))

    config_data["base_working_directory"] = str(tmp_path)
    for step in config_data["forward_model_steps"]:
        if step["executable"] == "poly_eval.py":
            step["executable"] = sys.executable
            step["args"] = [
                str(tmp_path / "poly_eval.py"),
                "--api-url",
                api_url,
            ] + step["args"]

    async with httpx.AsyncClient() as client:
        res = await client.post(f"{api_url}/experiments", json=config_data)
        assert res.status_code == 201
        experiment_id = res.json()["id"]

        # 2. Start
        res = await client.post(f"{api_url}/experiments/{experiment_id}/start")
        assert res.status_code == 200
        execution_id = res.json()["execution_id"]

        # 3. Poll
        max_wait = 60
        timeout_at = time.monotonic() + max_wait
        status = "RUNNING"
        while status == "RUNNING" and time.monotonic() < timeout_at:
            res = await client.get(
                f"{api_url}/experiments/{experiment_id}/executions/{execution_id}/state",
            )
            state = res.json()
            status = state["status"]
            if status in {"COMPLETED", "FAILED"}:
                break
            await asyncio.sleep(2)

        assert status == "COMPLETED"
        assert state["current_iteration"] == 3


@pytest.mark.asyncio
async def test_ert_poly_failing_update(
    tmp_path: Path,
    server_factory: Callable[[int, Path], tuple[subprocess.Popen[Any], Path]],
) -> None:
    """Test ert_poly with an algorithm update that raises an error, ensuring the orchestrator catches it and logs metadata.error."""
    port = get_free_port()
    api_url = f"http://127.0.0.1:{port}"

    example_dir = Path("examples/ert_poly")
    shutil.copytree(example_dir, tmp_path, dirs_exist_ok=True)

    server_factory(port, tmp_path)
    await wait_for_server(api_url)

    config_path = tmp_path / "experiment.json"
    config_data = json.loads(config_path.read_text(encoding="utf-8"))
    config_data["base_working_directory"] = str(tmp_path)

    # Force the algorithm to fail by giving it an invalid argument that will crash the math plugin
    config_data["updates"][0]["arguments"]["neighbor_propagation_order"] = (
        "INVALID_STRING_CAUSING_TYPE_ERROR"
    )

    for step in config_data["forward_model_steps"]:
        if step["executable"] == "poly_eval.py":
            step["executable"] = sys.executable
            step["args"] = [
                str(tmp_path / "poly_eval.py"),
                "--api-url",
                api_url,
            ] + step["args"]

    async with httpx.AsyncClient() as client:
        res = await client.post(f"{api_url}/experiments", json=config_data)
        experiment_id = res.json()["id"]
        res = await client.post(f"{api_url}/experiments/{experiment_id}/start")
        execution_id = res.json()["execution_id"]

        max_wait = 45
        timeout_at = time.monotonic() + max_wait
        status = "RUNNING"
        while status == "RUNNING" and time.monotonic() < timeout_at:
            res = await client.get(
                f"{api_url}/experiments/{experiment_id}/executions/{execution_id}/state",
            )
            state = res.json()
            status = state["status"]
            if status in {"COMPLETED", "FAILED"}:
                break
            await asyncio.sleep(1)

        # The orchestrator MUST fail the overarching execution.
        assert status == "FAILED"

        # Verify the update info endpoint properly exposes the error
        update_res = await client.get(
            f"{api_url}/experiments/{experiment_id}/executions/{execution_id}/ensembles/1/update/metadata",
        )
        if update_res.status_code != 200:
            print("Directory contents:")
            for p in tmp_path.glob("**/*"):
                print(p)
            print("Response:", update_res.json())
        assert update_res.status_code == 200
        update_metadata = update_res.json()

        assert update_metadata["status"] == "FAILED"
        assert "error" in update_metadata
        assert (
            "str" in update_metadata["error"]
            or "cannot be interpreted as an integer" in update_metadata["error"]
        )
        assert "Failed to write status event" not in update_metadata["error"]


@pytest.mark.asyncio
async def test_ert_poly_with_failures_and_tolerance(
    tmp_path: Path,
    server_factory: Callable[[int, Path], tuple[subprocess.Popen[Any], Path]],
) -> None:
    """Test ert_poly with some realizations failing, but within tolerance."""
    port = get_free_port()
    api_url = f"http://127.0.0.1:{port}"

    example_dir = Path("examples/ert_poly")
    shutil.copytree(example_dir, tmp_path, dirs_exist_ok=True)

    # Inject failure logic into poly_eval.py
    poly_eval_path = tmp_path / "poly_eval.py"
    content = poly_eval_path.read_text(encoding="utf-8")
    failure_logic = """
    if args.realization in [5, 10] and args.iteration == 1:
        raise RuntimeError("Simulated failure")
"""
    new_content = content.replace(
        "args = parser.parse_args()",
        "args = parser.parse_args()" + failure_logic,
    )
    poly_eval_path.write_text(new_content, encoding="utf-8")

    server_factory(port, tmp_path)
    await wait_for_server(api_url)

    config_path = tmp_path / "experiment.json"
    config_data = json.loads(config_path.read_text(encoding="utf-8"))

    config_data["base_working_directory"] = str(tmp_path)
    config_data["failure_tolerance"] = 0.2  # 20% tolerance

    for step in config_data["forward_model_steps"]:
        if step["executable"] == "poly_eval.py":
            step["executable"] = sys.executable
            step["args"] = [
                str(tmp_path / "poly_eval.py"),
                "--api-url",
                api_url,
            ] + step["args"]

    async with httpx.AsyncClient() as client:
        res = await client.post(f"{api_url}/experiments", json=config_data)
        experiment_id = res.json()["id"]
        res = await client.post(f"{api_url}/experiments/{experiment_id}/start")
        execution_id = res.json()["execution_id"]

        max_wait = 60
        timeout_at = time.monotonic() + max_wait
        status = "RUNNING"
        while status == "RUNNING" and time.monotonic() < timeout_at:
            res = await client.get(
                f"{api_url}/experiments/{experiment_id}/executions/{execution_id}/state",
            )
            state = res.json()
            status = state["status"]
            if status in {"COMPLETED", "FAILED"}:
                break
            await asyncio.sleep(2)

        # Should still complete because 2/20 = 10% < 20% tolerance
        assert status == "COMPLETED"
        assert state["current_iteration"] == 3
