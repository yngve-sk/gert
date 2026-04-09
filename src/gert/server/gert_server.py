"""GERT server application."""

import logging
import pathlib
import socket

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from gert.server.models import ConnectionInfo
from gert.server.router import router

pathlib.Path("logs").mkdir(exist_ok=True, parents=True)


def get_free_port() -> int:
    """Get a random free port from the OS."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return int(s.getsockname()[1])


def configure_server_logging() -> None:
    """Configure logging for the GERT server."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        handlers=[
            logging.FileHandler("logs/gert.log", mode="w"),
            logging.FileHandler("logs/combined.log", mode="a"),
            logging.StreamHandler(),
        ],
        force=True,  # Ensure we override any existing handlers
    )


def create_gert_server(conn_info: ConnectionInfo | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""

    gert_server_app = FastAPI(
        title="GERT API Server",
        description="Generic Ensemble Reservoir Tool orchestration API.",
        version="0.1.0",
    )
    gert_server_app.state.connection_info = conn_info
    gert_server_app.include_router(router)

    # M12: Mount the compiled SvelteKit GUI
    static_dir = pathlib.Path(__file__).parent / "static"
    if static_dir.exists() and (static_dir / "index.html").exists():
        gert_server_app.mount(
            "/_app",
            StaticFiles(directory=str(static_dir / "_app")),
            name="app",
        )

        @gert_server_app.get("/{full_path:path}")
        async def serve_svelte_gui(full_path: str) -> FileResponse | None:
            """Serve the SvelteKit SPA fallback."""
            # Ensure API paths fall through
            if full_path.startswith(("experiments", "logs")):
                return None
            physical_path = static_dir / full_path
            if physical_path.is_file():
                return FileResponse(physical_path)
            return FileResponse(static_dir / "index.html")

    return gert_server_app


gert_server_app = create_gert_server()
