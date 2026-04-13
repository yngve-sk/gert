"""GERT server application."""

import logging
import pathlib
import socket

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from gert.server.models import ConnectionInfo
from gert.server.router import router

pathlib.Path("logs").mkdir(exist_ok=True, parents=True)

logger = logging.getLogger(__name__)


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

    @gert_server_app.exception_handler(Exception)
    def global_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        logger.error(f"Unhandled exception on {request.url.path}", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Internal Server Error: {exc!s}"},
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

        @gert_server_app.exception_handler(404)
        def custom_404_handler(
            request: Request,
            exc: Exception,
        ) -> FileResponse | JSONResponse:
            """Serve the SvelteKit SPA fallback for unhandled routes."""
            path = request.url.path
            accept = request.headers.get("accept", "")

            # If it's a browser navigation request, always serve the SPA
            if "text/html" in accept:
                return FileResponse(static_dir / "index.html")

            # Otherwise, preserve the 404 JSON response for API calls
            if path.startswith(
                ("/experiments", "/logs", "/system", "/connection-info"),
            ):
                detail = "Not Found"
                if hasattr(exc, "detail"):
                    detail = exc.detail
                return JSONResponse({"detail": detail}, status_code=404)

            path_stripped = path.lstrip("/")
            physical_path = static_dir / path_stripped
            # Serve specific static files if they exist (e.g. /favicon.png)
            if physical_path.is_file():
                return FileResponse(physical_path)

            # Ultimate fallback to SPA index.html
            return FileResponse(static_dir / "index.html")

    return gert_server_app


gert_server_app = create_gert_server()
