"""Tests for the monitoring API."""

import pytest
from fastapi.testclient import TestClient

from gert.server.gert_server import create_gert_server
from gert.server.router import RealizationStatus, _experiment_statuses


@pytest.fixture
def test_client() -> TestClient:
    """Fixture to provide a test client for the FastAPI app."""
    app = create_gert_server()
    return TestClient(app)


def test_monitoring_api_get_status(test_client: TestClient) -> None:
    """Test the GET endpoint for experiment status."""
    experiment_id = "test-exp-2"
    _experiment_statuses[experiment_id][0] = RealizationStatus(
        realization_id=0,
        iteration=1,
        status="COMPLETED",
    )

    response = test_client.get(f"/experiments/{experiment_id}/status")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["realization_id"] == 0
    assert data[0]["iteration"] == 1
    assert data[0]["status"] == "COMPLETED"
