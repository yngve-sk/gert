import asyncio
import shutil
from collections.abc import Generator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from gert.server.gert_server import gert_server_app


@pytest.fixture
def clean_storage() -> Generator[None, None, None]:
    """Fixture to clean up the storage directory before and after tests."""
    storage_path = Path("./gert_storage")
    if storage_path.exists():
        shutil.rmtree(storage_path)
    yield
    if storage_path.exists():
        shutil.rmtree(storage_path)


def test_storage_integration_blast(clean_storage: None) -> None:
    """Blast 100 concurrent payloads and verify consolidation."""
    client = TestClient(gert_server_app)
    experiment_id = "blast-test"

    # 1. Ingest 100 payloads
    payloads = [
        {
            "realization": i,
            "source_step": "step1",
            "key": {"response": "FOPR"},
            "value": float(100 + i),
        }
        for i in range(100)
    ]

    for payload in payloads:
        response = client.post(
            f"/storage/{experiment_id}/ingest",
            json=payload,
        )
        assert response.status_code == 202

    # 2. Retrieve responses (this triggers consolidation in the route)
    response = client.get(f"/storage/{experiment_id}/responses")
    assert response.status_code == 200

    data = response.json()
    assert len(data) == 100

    # Verify a few values
    # The order might not be guaranteed depending on how polars reads ndjson,
    # but we should have all 100 realizations.
    realizations = [item["realization"] for item in data]
    assert set(realizations) == set(range(100))


@pytest.mark.asyncio
async def test_storage_integration_concurrent_blast(clean_storage: None) -> None:
    """Blast 100 payloads concurrently using httpx.AsyncClient."""
    # TestClient doesn't support true concurrency in the same way,
    # but we can use httpx.AsyncClient with the app.
    experiment_id = "concurrent-blast-test"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gert_server_app),
        base_url="http://test",
    ) as ac:
        tasks = []
        for i in range(100):
            payload = {
                "realization": i,
                "source_step": "step1",
                "key": {"response": "FOPR"},
                "value": float(100 + i),
            }
            tasks.append(ac.post(f"/storage/{experiment_id}/ingest", json=payload))

        responses = await asyncio.gather(*tasks)

    for response in responses:
        assert response.status_code == 202

    # Verify via regular TestClient
    client = TestClient(gert_server_app)
    response = client.get(f"/storage/{experiment_id}/responses")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 100
