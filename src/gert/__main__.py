# ruff: noqa: S404, S603
"""GERT Command Line Interface."""

import argparse
import json
import logging
import os
import secrets
import subprocess
import sys
import time
import webbrowser
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx
import uvicorn

from gert.discovery import (
    NoGertServerFoundError,
    find_gert_server,
    get_discovery_file,
    wait_for_gert_server,
)
from gert.experiments.models import (
    ParameterMatrix,
)
from gert.monitor import start_monitor
from gert.server.gert_server import (
    configure_server_logging,
    create_gert_server,
    get_free_port,
)
from gert.server.models import ConnectionInfo

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
    api_url: str | None,
) -> tuple[subprocess.Popen[Any] | None, str]:
    """Ensure the GERT server is running, starting it if necessary."""
    if api_url:
        try:
            client.base_url = api_url
            client.get("/docs")
        except httpx.ConnectError:
            print(f"Server not found at {api_url}, scanning for server...")
        else:
            return None, api_url

    try:
        info = find_gert_server()
        url = info.base_url
        print(f"Found running GERT server at {url}")
    except NoGertServerFoundError:
        print("No running GERT server found. Starting temporary server...")
        port = get_free_port()
        host = "127.0.0.1"
        url = f"http://{host}:{port}"
        client.base_url = url

        server_process = subprocess.Popen(
            [sys.executable, "-m", "gert", "server", "--port", str(port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        try:
            wait_for_gert_server(timeout=15)
        except NoGertServerFoundError:
            print("Failed to start temporary server.", file=sys.stderr)
            server_process.terminate()
            sys.exit(1)

        return server_process, url
    else:
        client.base_url = url
        return None, url


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
    api_url: str | None,
    *,
    wait_for_completion: bool = False,
    monitor: bool = False,
) -> None:
    """Run an experiment by submitting it to the GERT API."""
    config_data = _load_config(config_path)
    server_process = None
    client = httpx.Client()

    try:
        server_process, resolved_api_url = _ensure_server(client, api_url)
        print(f"Submitting '{config_path}' to GERT server at {resolved_api_url}...")
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

            # Inject API URL and Auth Token into forward model arguments
            connection_info = find_gert_server()
            for step in config_data["forward_model_steps"]:
                step["args"].extend(
                    [
                        "--api-url",
                        connection_info.base_url,
                        "--auth-token",
                        connection_info.token,
                    ],
                )

            if monitor:
                start_monitor(
                    resolved_api_url,
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
                    f"{resolved_api_url}/experiments/{config_id}/executions/{execution_id}"
                    f"/ensembles/{last_it}/responses",
                )

        except httpx.ConnectError:
            print(
                f"❌ Connection error: Could not connect to GERT server at "
                f"{resolved_api_url}.",
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


def handle_connection_info() -> None:
    """Handle the 'gert connection info' command."""
    try:
        info = find_gert_server()
        print("✅ Found running GERT server.")
        print(f"  {'Host':<10}: {info.host}")
        print(f"  {'Port':<10}: {info.port}")
        print(f"  {'Base_url':<10}: {info.base_url}")
        print(f"  {'Token':<10}: {info.token}")
        print(f"  {'Server_id':<10}: {info.server_id}")
        print(f"  {'Pid':<10}: {info.pid}")
        print(f"  {'Version':<10}: {info.version}")
    except NoGertServerFoundError:
        print("❌ No running GERT server found.", file=sys.stderr)
        sys.exit(1)


def handle_connection_url() -> None:
    """Handle the 'gert connection url' command."""
    try:
        info = find_gert_server()
        print(info.base_url)
    except NoGertServerFoundError:
        print("❌ No running GERT server found.", file=sys.stderr)
        sys.exit(1)


def handle_connection_token() -> None:
    """Handle the 'gert connection token' command."""
    try:
        info = find_gert_server()
        print(info.token)
    except NoGertServerFoundError:
        print("❌ No running GERT server found.", file=sys.stderr)
        sys.exit(1)


def handle_connection_wait() -> None:
    """Handle the 'gert connection wait' command."""
    print("Waiting for GERT server to become available...")
    try:
        wait_for_gert_server()
        print("✅ GERT server is available.")
    except NoGertServerFoundError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)


def _handle_run_command(args: argparse.Namespace) -> None:
    """Handle the 'gert run' command."""
    run_experiment(
        args.config,
        args.api_url,
        wait_for_completion=args.wait,
        monitor=args.monitor,
    )


def _handle_server_command(args: argparse.Namespace) -> None:
    """Handle the 'gert server' command."""
    configure_server_logging()
    port = args.port if args.port != 0 else get_free_port()
    host = args.host
    pid = os.getpid()

    connection_info = ConnectionInfo(
        host=host,
        port=port,
        base_url=f"http://{host}:{port}",
        token=f"gert_{secrets.token_hex(16)}",
        server_id=f"gert_{pid}_{int(time.time())}",
        pid=pid,
    )

    try:
        discovery_file = get_discovery_file()
        discovery_file.parent.mkdir(parents=True, exist_ok=True)
        with discovery_file.open("w", encoding="utf-8") as f:
            f.write(connection_info.model_dump_json(indent=2))
        print(f"Starting GERT server on {host}:{port}...")
        gert_app = create_gert_server(conn_info=connection_info)
        uvicorn.run(
            gert_app,
            host=host,
            port=port,
            reload=args.reload,
        )
    finally:
        if discovery_file.exists():
            discovery_file.unlink()


def _handle_monitor_command(args: argparse.Namespace) -> None:
    """Handle the 'gert monitor' command."""
    client = httpx.Client()
    server_process = None
    try:
        server_process, resolved_api_url = _ensure_server(client, args.api_url)
        start_monitor(resolved_api_url, args.experiment_id)
    finally:
        client.close()
        if server_process:
            server_process.terminate()
            server_process.wait()


def _handle_connect_command(args: argparse.Namespace) -> None:
    """Handle the 'gert connect' command."""
    config_data = _load_config(args.config)
    exp_name = config_data["name"]

    client = httpx.Client()
    server_process = None
    try:
        server_process, resolved_api_url = _ensure_server(client, args.api_url)
        client.base_url = resolved_api_url

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
            print(
                f"Experiment '{exp_name}' not recognized by server. "
                f"Registering configuration...",
            )
            resp = client.post("/experiments", json=config_data)
            resp.raise_for_status()
            experiment_id = resp.json()["id"]

        start_monitor(resolved_api_url, experiment_id)
    except (httpx.ConnectError, NoGertServerFoundError):
        print(
            "❌ Connection error: Could not connect to a GERT server.",
            file=sys.stderr,
        )
        sys.exit(1)
    finally:
        client.close()
        if server_process is not None:
            print("Shutting down temporary server...")
            server_process.terminate()
            server_process.wait()


def _handle_connection_subcommands(args: argparse.Namespace) -> None:
    """Handle 'gert connection' subcommands."""
    if args.connection_command == "info":
        handle_connection_info()
    elif args.connection_command == "url":
        handle_connection_url()
    elif args.connection_command == "token":
        handle_connection_token()
    elif args.connection_command == "wait":
        handle_connection_wait()


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the GERT CLI."""
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
        default=None,
        help="Base URL of the GERT server (if not provided, will scan for server)",
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
        default=0,
        help="Port to bind to (default: 0, means auto-select)",
    )
    server_parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development",
    )

    # `gert monitor`
    monitor_parser = subparsers.add_parser(
        "monitor",
        help="Monitor a running GERT experiment",
    )
    monitor_parser.add_argument(
        "experiment_id",
        type=str,
        help="The ID of the experiment to monitor",
    )
    monitor_parser.add_argument(
        "--api-url",
        default=None,
        help="Base URL of the GERT server (if not provided, will scan for server)",
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
        default=None,
        help="Base URL of the GERT server (if not provided, will scan for server)",
    )

    # `gert connection`
    conn_parser = subparsers.add_parser(
        "connection",
        help="Commands for server service discovery",
    )
    conn_subparsers = conn_parser.add_subparsers(
        dest="connection_command",
        required=True,
    )
    conn_subparsers.add_parser("info", help="Show full connection details with status")
    conn_subparsers.add_parser("url", help="Print just base_url for scripts")
    conn_subparsers.add_parser("token", help="Print just auth token for scripts")
    conn_subparsers.add_parser("wait", help="Wait for server to become available")

    # GUI Command
    ui_parser = subparsers.add_parser(
        "ui",
        help="Launch the GERT Web GUI",
        description="Connects to the GERT server and opens the web GUI.",
    )
    ui_parser.add_argument(
        "--api-url",
        type=str,
        default=None,
        help="Explicit URL of the GERT server to connect to (overrides discovery).",
    )
    ui_parser.add_argument(
        "--server-id",
        type=str,
        default=None,
        help="Server ID to connect to (if not provided, uses the first found server).",
    )

    return parser.parse_args()


def _handle_ui_command(args: argparse.Namespace) -> None:
    """Launch the Web GUI server and open the browser."""
    logger = logging.getLogger("gert.cli")

    client = httpx.Client()
    server_process = None
    try:
        # Implicitly discover or start a server
        server_process, resolved_api_url = _ensure_server(client, args.api_url)

        url = f"{resolved_api_url}/"
        logger.info(f"Opening GERT Web GUI at {url}")
        print(f"Opening GERT Web GUI at {url}")

        webbrowser.open(url)

        if server_process:
            print("Running temporary GERT server. Press Ctrl+C to stop.")
            # Block until the user kills the process
            server_process.wait()

    except KeyboardInterrupt:
        print("\nShutting down GERT UI server...")
    except Exception:
        logger.exception("Failed to launch UI")
        sys.exit(1)
    finally:
        client.close()
        if server_process:
            server_process.terminate()
            server_process.wait()


def main() -> None:
    """Entry point for the GERT CLI."""
    args = _parse_args()

    if args.command == "run":
        _handle_run_command(args)
    elif args.command == "server":
        _handle_server_command(args)
    elif args.command == "ui":
        _handle_ui_command(args)
    elif args.command == "monitor":
        _handle_monitor_command(args)
    elif args.command == "connect":
        _handle_connect_command(args)
    elif args.command == "connection":
        _handle_connection_subcommands(args)


if __name__ == "__main__":
    main()
