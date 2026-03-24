"""GERT server application."""

from fastapi import FastAPI

from gert.server.router import router


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
