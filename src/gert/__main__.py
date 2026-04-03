# ruff: noqa: S404, S603
"""GERT Command Line Interface."""

import argparse
import json
import logging
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import uvicorn

from gert.experiments.models import (
    ParameterMatrix,
)
from gert.monitor import start_monitor

log = logging.getLogger(__name__)


def _get_expected_realizations(config_data: dict[str, Any]) -> int:
    """Calculate the number of unique realizations expected."""
    # Attempt to instantiate ParameterMatrix to use its robust get_realizations
    try:
        pm = ParameterMatrix(**config_data.get("parameter_matrix", {}))
        base_dir_str = config_data.get("base_working_directory", ".")
        reals = pm.get_realizations(Path(base_dir_str))
        if reals:
            return len(reals)
    except Exception as e:  # noqa: BLE001
        log.warning(
            "Could not calculate expected realizations from ParameterMatrix: %s",
            e,
        )

    # Fallback to reading values dict
    realizations = set()
    values = config_data.get("parameter_matrix", {}).get("values", {})
    for param_values in values.values():
        realizations.update(param_values.keys())
    return len(realizations)


def _load_config(config_path: Path) -> dict[str, Any]:
    """Load and preprocess the experiment configuration."""
    if not config_path.exists():
        print(f"Error: Configuration file '{config_path}' not found.", file=sys.stderr)
        sys.exit(1)

    try:
        with config_path.open(encoding="utf-8") as f:
            config_data: dict[str, Any] = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON configuration: {e}", file=sys.stderr)
        sys.exit(1)

    config_dir = config_path.parent.resolve()
    if config_data.get("base_working_directory") in {None, ".", ""}:
        config_data["base_working_directory"] = str(config_dir)

    return config_data


def _ensure_server(
    client: httpx.Client,
    api_url: str,
) -> subprocess.Popen[Any] | None:
    """Ensure the GERT server is running, starting it if necessary."""
    try:
        client.get("/docs")
    except httpx.ConnectError:
        print(f"Server not running at {api_url}. Starting temporary server...")
        parsed_url = urlparse(api_url)
        host = parsed_url.hostname or "127.0.0.1"
        port = parsed_url.port or 8000

        server_process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "gert",
                "server",
                "--host",
                host,
                "--port",
                str(port),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        max_retries = 300
        for i in range(max_retries):
            try:
                client.get("/docs")
            except httpx.ConnectError:
                if i == max_retries - 1:
                    print("Failed to start temporary server.", file=sys.stderr)
                    server_process.terminate()
                    sys.exit(1)
                time.sleep(0.1)
            else:
                return server_process
    else:
        return None
    return None


def _check_execution_state(
    client: httpx.Client,
    experiment_id: str,
    execution_id: str,
) -> None:
    """Check overall execution state and exit if failed."""
    state_resp = client.get(
        f"/experiments/{experiment_id}/executions/{execution_id}/state",
    )
    state_resp.raise_for_status()
    exec_state = state_resp.json()
    if exec_state["status"] == "FAILED":
        err_msg = exec_state.get("error", "Unknown error")
        print(
            f"\n❌ Execution Failed in background process:\n{err_msg}",
            file=sys.stderr,
        )
        sys.exit(1)


def _poll_for_completion(
    client: httpx.Client,
    experiment_id: str,
    execution_id: str,
    num_iterations: int,
    expected_count: int,
) -> None:
    """Poll the API until all iterations are completed."""
    print(f"\nWaiting for {num_iterations} iterations to complete...")
    completed_iterations: set[int] = set()

    while len(completed_iterations) < num_iterations:
        try:
            _check_execution_state(client, experiment_id, execution_id)

            resp = client.get(
                f"/experiments/{experiment_id}/executions/{execution_id}/status",
            )
            resp.raise_for_status()
            statuses = resp.json()

            iter_counts: dict[int, int] = defaultdict(int)
            for s in statuses:
                if s["status"] in {"COMPLETED", "FAILED"}:
                    iter_counts[s["iteration"]] += 1

            for it in range(num_iterations):
                if it not in completed_iterations and iter_counts[it] >= expected_count:
                    print(f"✅ Iteration {it} completed.")
                    completed_iterations.add(it)

            if len(completed_iterations) < num_iterations:
                time.sleep(1)
        except (httpx.HTTPError, KeyError, ValueError) as e:
            print(f"Polling error: {e}")
            time.sleep(1)

        time.sleep(0.1)


def run_experiment(
    config_path: Path,
    api_url: str,
    *,
    wait_for_completion: bool = False,
    monitor: bool = False,
) -> None:
    """Run an experiment by submitting it to the GERT API."""
    config_data = _load_config(config_path)
    server_process = None
    client = httpx.Client(base_url=api_url)

    try:
        server_process = _ensure_server(client, api_url)
        print(f"Submitting '{config_path}' to GERT server at {api_url}...")
        try:
            # 1. Register the experiment
            response = client.post("/experiments", json=config_data)
            response.raise_for_status()
            config_id = response.json()["id"]
            print(f"✅ Experiment registered (Config ID: {config_id})")

            # 2. Start the execution
            response = client.post(f"/experiments/{config_id}/start")
            response.raise_for_status()
            res_json = response.json()
            execution_id = res_json["execution_id"]
            num_iterations = len(config_data.get("updates", [])) + 1
            print(
                f"✅ Execution started (Execution ID: {execution_id}, "
                f"Total Iterations: {num_iterations})",
            )

            if monitor:
                start_monitor(
                    api_url,
                    config_id,
                    execution_id,
                )
            elif server_process is not None or wait_for_completion:
                expected_count = _get_expected_realizations(config_data)
                _poll_for_completion(
                    client,
                    config_id,
                    execution_id,
                    num_iterations,
                    expected_count,
                )
            else:
                last_it = num_iterations - 1
                print("\nExperiment is running in the background.")
                print("You can query the consolidated responses using:")
                print(
                    f"  curl "
                    f"{api_url}/experiments/{config_id}/executions/{execution_id}"
                    f"/ensembles/{last_it}/responses",
                )

        except httpx.ConnectError:
            print(
                f"❌ Connection error: Could not connect to GERT server at {api_url}.",
                file=sys.stderr,
            )
            sys.exit(1)
        except httpx.HTTPStatusError as e:
            print(
                f"❌ API error ({e.response.status_code}): {e.response.text}",
                file=sys.stderr,
            )
            sys.exit(1)

    finally:
        client.close()
        if server_process is not None:
            print("Shutting down temporary server...")
            server_process.terminate()
            server_process.wait()


def main() -> None:
    """Entry point for the GERT CLI."""
    parser = argparse.ArgumentParser(
        description="GERT - Generic Ensemble Reservoir Tool CLI",
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        help="Command to execute",
    )

    # `gert run`
    run_parser = subparsers.add_parser(
        "run",
        help="Run a GERT experiment configuration",
    )
    run_parser.add_argument(
        "config",
        type=Path,
        help="Path to the experiment configuration JSON file",
    )
    run_parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="Base URL of the GERT server (default: http://localhost:8000)",
    )
    run_parser.add_argument(
        "--wait",
        action="store_true",
        help="Wait for the experiment to complete",
    )
    run_parser.add_argument(
        "--monitor",
        action="store_true",
        help="Open the live monitor dashboard for this run",
    )

    # `gert server`
    server_parser = subparsers.add_parser("server", help="Start the GERT API server")
    server_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)",
    )
    server_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind to (default: 8000)",
    )
    server_parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development",
    )

    # `gert monitor` (deprecated/alias for backward compatibility without execution_id)
    monitor_parser = subparsers.add_parser(
        "monitor",
        help="Monitor an running GERT experiment",
    )
    monitor_parser.add_argument(
        "experiment_id",
        type=str,
        help="The ID of the experiment to monitor",
    )
    monitor_parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="Base URL of the GERT server (default: http://localhost:8000)",
    )

    # `gert connect`
    connect_parser = subparsers.add_parser(
        "connect",
        help="Connect the monitor to existing experiment executions",
    )
    connect_parser.add_argument(
        "config",
        type=Path,
        help="Path to the experiment configuration JSON file",
    )
    connect_parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="Base URL of the GERT server (default: http://localhost:8000)",
    )

    args = parser.parse_args()

    if args.command == "run":
        run_experiment(
            args.config,
            args.api_url,
            wait_for_completion=args.wait,
            monitor=args.monitor,
        )
    elif args.command == "server":
        print(f"Starting GERT server on {args.host}:{args.port}...")
        uvicorn.run(
            "gert.server.gert_server:gert_server_app",
            host=args.host,
            port=args.port,
            reload=args.reload,
        )
    elif args.command == "monitor":
        start_monitor(args.api_url, args.experiment_id)
    elif args.command == "connect":
        config_data = _load_config(args.config)
        exp_name = config_data["name"]

        client = httpx.Client(base_url=args.api_url)
        server_process = None
        try:
            server_process = _ensure_server(client, args.api_url)

            # Find experiment ID by name
            resp = client.get("/experiments")
            resp.raise_for_status()
            experiments = resp.json()

            experiment_id = None
            for exp in experiments:
                if exp["name"] == exp_name:
                    experiment_id = exp["id"]
                    break

            if not experiment_id:
                # If not found, register it now to make it known to the server.
                # (Even if it's already in storage, registering ensures it's in memory)
                print(
                    f"Experiment '{exp_name}' not recognized by server. "
                    f"Registering configuration...",
                )
                resp = client.post("/experiments", json=config_data)
                resp.raise_for_status()
                experiment_id = resp.json()["id"]

            start_monitor(args.api_url, experiment_id)
        except httpx.ConnectError:
            print(
                f"❌ Connection error: Could not connect to "
                f"GERT server at {args.api_url}.",
                file=sys.stderr,
            )
            sys.exit(1)
        finally:
            client.close()
            if server_process is not None:
                print("Shutting down temporary server...")
                server_process.terminate()
                server_process.wait()


if __name__ == "__main__":
    main()
