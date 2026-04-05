"""GERT server application."""

import logging
import pathlib

from fastapi import FastAPI

from gert.server.router import router

pathlib.Path("logs").mkdir(exist_ok=True, parents=True)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/gert.log", mode="w"),
        logging.FileHandler("logs/combined.log", mode="a"),
        logging.StreamHandler(),
    ],
)


def create_gert_server() -> FastAPI:
    """Create and configure the FastAPI application."""
    gert_server_app = FastAPI(
        title="GERT API Server",
        description="Generic Ensemble Reservoir Tool orchestration API.",
        version="0.1.0",
    )

    gert_server_app.include_router(router)

    return gert_server_app


gert_server_app = create_gert_server()
