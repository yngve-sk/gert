import json
import os
import time
from pathlib import Path

import httpx
import psutil

from gert.server.models import ConnectionInfo


def get_discovery_file() -> Path:
    return (
        Path(os.environ.get("GERT_DISCOVERY_DIR", Path.home() / ".gert"))
        / "server_info.json"
    )


class NoGertServerFoundError(RuntimeError):
    """Raised when no GERT server can be found."""

    MSG_NO_FILE = "No GERT server discovery file found."
    MSG_READ_PARSE_ERROR = "Could not read or parse discovery file."
    MSG_STALE_FILE_PROCESS_GONE = (
        "Stale discovery file. The process is no longer running."
    )
    MSG_SERVER_NOT_RESPONSIVE = "Found server in file, but it is not responsive yet."
    MSG_SERVER_MISMATCH = "Server responded with non-matching info."
    MSG_INVALID_INFO_FILE = "Invalid connection info in file."
    MSG_TIMEOUT = "GERT server not found within {timeout}s"


def _is_server_process_alive(pid: int) -> bool:
    """Check if the server process with the given PID is running."""
    try:
        return psutil.Process(pid).is_running()
    except psutil.NoSuchProcess:
        return False


def find_gert_server() -> ConnectionInfo:
    """
    Find the running GERT server by reading the discovery file.

    Returns:
        The connection information dictionary from the responsive server.

    Raises:
        NoGertServerFoundError: If no server is found or the existing one is stale.
    """
    discovery_file = get_discovery_file()
    if not discovery_file.exists():
        raise NoGertServerFoundError(NoGertServerFoundError.MSG_NO_FILE)

    try:
        with discovery_file.open("r", encoding="utf-8") as f:
            info_dict = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        msg = NoGertServerFoundError.MSG_READ_PARSE_ERROR.format(e=e)
        raise NoGertServerFoundError(msg) from e

    pid = info_dict.get("pid")
    if not pid or not _is_server_process_alive(pid):
        discovery_file.unlink()  # Stale file because the process is gone
        raise NoGertServerFoundError(NoGertServerFoundError.MSG_STALE_FILE_PROCESS_GONE)

    try:
        # Validate the dictionary against the ConnectionInfo model
        connection_info = ConnectionInfo.model_validate(info_dict)
        with httpx.Client(base_url=connection_info.base_url, timeout=1.0) as client:
            resp = client.get("/connection-info")
            if (
                resp.status_code == 200
                and resp.json()["server_id"] == connection_info.server_id
            ):
                return connection_info
            # If the server responds with a non-matching ID, something is very wrong.
            raise NoGertServerFoundError(NoGertServerFoundError.MSG_SERVER_MISMATCH)
    except httpx.ConnectError as e:
        # Don't delete the file here. The server might just be starting up.
        # Let the waiter function handle retries.
        raise NoGertServerFoundError(
            NoGertServerFoundError.MSG_SERVER_NOT_RESPONSIVE,
        ) from e
    except Exception as e:
        msg = NoGertServerFoundError.MSG_INVALID_INFO_FILE.format(e=e)
        raise NoGertServerFoundError(msg) from e


def wait_for_gert_server(timeout: int = 30) -> ConnectionInfo:
    """
    Wait for a GERT server to become available.

    Args:
        timeout: The maximum time to wait in seconds.

    Returns:
        The connection information dictionary from the server.

    Raises:
        NoGertServerFoundError: If no server is found within the timeout.
    """
    end_time = time.monotonic() + timeout
    while time.monotonic() < end_time:
        try:
            return find_gert_server()
        except NoGertServerFoundError:
            time.sleep(0.2)
    raise NoGertServerFoundError(
        NoGertServerFoundError.MSG_TIMEOUT.format(timeout=timeout),
    )
