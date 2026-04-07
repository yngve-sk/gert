"""Pydantic models for the GERT server."""

from pydantic import BaseModel, Field


class ConnectionInfo(BaseModel):
    """Server connection details."""

    host: str = Field(..., description="The server host.")
    port: int = Field(..., description="The server port.")
    base_url: str = Field(..., description="The server base URL.")
    token: str = Field(..., description="The authentication token.")
    server_id: str = Field(..., description="The unique server ID.")
    pid: int = Field(..., description="The server process ID.")
    version: str = Field(default="0.1.0", description="The GERT version.")
