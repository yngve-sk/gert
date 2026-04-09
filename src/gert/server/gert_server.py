"""GERT server application."""

import logging
import pathlib
import socket

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

    gert_server_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    gert_server_app.state.connection_info = conn_info
    gert_server_app.include_router(router)

    return gert_server_app


gert_server_app = create_gert_server()
