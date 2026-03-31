import asyncio
import shutil
from collections.abc import Generator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from gert.server.gert_server import gert_server_app
from gert.storage.consolidation import ConsolidationWorker


@pytest.fixture
def clean_storage() -> Generator[None]:
    """Fixture to clean up the storage directory before and after tests."""
    storage_path = Path("./permanent_storage")
    if storage_path.exists():
        shutil.rmtree(storage_path)
    yield
    if storage_path.exists():
        shutil.rmtree(storage_path)


async def test_storage_integration_blast(clean_storage: None) -> None:
    """Blast 100 concurrent payloads and verify consolidation."""
    client = TestClient(gert_server_app)

    # Register an experiment
    config_data = {
        "name": "blast-test",
        "base_working_directory": ".",
        "forward_model_steps": [{"executable": "/bin/echo", "name": "e"}],
        "queue_config": {"backend": "local", "custom_attributes": {}},
        "parameter_matrix": {"metadata": {}, "values": {}, "datasets": []},
        "observations": [],
    }
    response = client.post("/experiments", json=config_data)
    assert response.status_code == 201
    experiment_id = response.json()["id"]
    # For storage tests, execution_id can be the same as experiment_id
    # but the API now requires both in the path.

    start_resp = client.post(f"/experiments/{experiment_id}/start")
    assert start_resp.status_code == 200
    execution_id = start_resp.json()["execution_id"]

    experiment_name = "blast-test"

    iteration = 0

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
            f"/experiments/{experiment_id}/executions/{execution_id}/ensembles/{iteration}/ingest",
            json=payload,
        )
        assert response.status_code == 202

    ensemble_path = (
        Path("./permanent_storage")
        / experiment_name
        / execution_id
        / f"iter-{iteration}"
    )
    worker = ConsolidationWorker.get_instance(ensemble_path)
    await worker.consolidate()

    # 2. Retrieve responses
    response = client.get(
        f"/experiments/{experiment_id}/executions/{execution_id}/ensembles/{iteration}/responses",
    )
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
    client = TestClient(gert_server_app)
    config_data = {
        "name": "concurrent-blast-test",
        "base_working_directory": ".",
        "forward_model_steps": [{"executable": "/bin/echo", "name": "e"}],
        "queue_config": {"backend": "local", "custom_attributes": {}},
        "parameter_matrix": {"metadata": {}, "values": {}, "datasets": []},
        "observations": [],
    }
    response = client.post("/experiments", json=config_data)
    assert response.status_code == 201
    experiment_id = response.json()["id"]

    start_resp = client.post(f"/experiments/{experiment_id}/start")
    assert start_resp.status_code == 200
    execution_id = start_resp.json()["execution_id"]

    experiment_name = "concurrent-blast-test"

    iteration = 0

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
            tasks.append(
                ac.post(
                    f"/experiments/{experiment_id}/executions/{execution_id}/ensembles/{iteration}/ingest",
                    json=payload,
                ),
            )

        responses = await asyncio.gather(*tasks)

    for response in responses:
        assert response.status_code == 202

    ensemble_path = (
        Path("./permanent_storage")
        / experiment_name
        / execution_id
        / f"iter-{iteration}"
    )
    worker = ConsolidationWorker.get_instance(ensemble_path)
    await worker.consolidate()

    # Verify via regular TestClient
    client = TestClient(gert_server_app)
    response = client.get(
        f"/experiments/{experiment_id}/executions/{execution_id}/ensembles/{iteration}/responses",
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 100
