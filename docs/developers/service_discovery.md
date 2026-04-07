# GERT Service Discovery Implementation

This document outlines the implementation of an API-based service discovery system for GERT. This approach uses a well-known file to share connection details, avoiding port scanning and providing a robust discovery mechanism.

## Core Requirements

### 1. Server Behavior

-   **Dynamic Port Assignment**: The server automatically selects an available port on startup (`port=0`).
-   **Connection File**: Upon starting, the server writes its connection details to a well-known file located at `~/.gert/server_info.json`.
-   **Connection Info Structure**: The file contains a JSON payload with the following structure:
    ```json
    {
      "host": "127.0.0.1",
      "port": 12345,
      "base_url": "http://127.0.0.1:12345",
      "token": "auth_token",
      "server_id": "gert_<pid>_<timestamp>",
      "pid": 12345,
      "version": "1.0"
    }
    ```
-   **Automatic Cleanup**: The server automatically deletes the `server_info.json` file upon clean shutdown.

### 2. Service Discovery Function

A `find_gert_server() -> dict` function is implemented to:

-   Read the connection details from `~/.gert/server_info.json`.
-   Verify that the server process ID (`pid`) listed in the file is still running.
-   Ping the server's health check or docs endpoint to confirm it's responsive.
-   If the file is missing, the process is dead, or the server is unresponsive, it raises a `NoGertServerFound` error and cleans up any stale files.
-   Return the connection information dictionary if the server is validated.

### 3. CLI Commands

The following CLI commands use the service discovery function to find the server:

```shell
gert connection info     # Show full connection details with status
gert connection url      # Print just base_url for scripts
gert connection token    # Print just auth token for scripts
gert connection wait     # Wait for a server to become available
```

### 4. Test Integration

A `wait_for_gert_server(timeout=30) -> dict` helper is implemented to:

-   Repeatedly call `find_gert_server()` until a server is found or the timeout is reached.
-   This helper is used in integration tests to reliably discover the server's connection info.

### 5. Forward Model Integration

The orchestrator discovers the server connection details and injects them as explicit arguments to the forward models:

```python
# Orchestrator discovers connection and injects into forward model args
connection_info = find_gert_server()
for step in config_data["forward_model_steps"]:
    step["args"].extend([
        "--api-url", connection_info["base_url"],
        "--auth-token", connection_info["token"]
    ])
```

## Key Design Principles

-   **Single Server Assumption**: The design assumes only one GERT server is running per machine, managed via the well-known file.
-   **File-Based Discovery**: Service discovery relies on a single, automatically managed file, avoiding port scanning.
-   **Robustness**: The client validates that the server is alive before using the connection info, and cleans up stale files.
-   **Developer-Friendly CLI**: The CLI commands work transparently without needing connection details.
