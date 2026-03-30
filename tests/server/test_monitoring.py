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
    execution_id = "run_1-test"
    _experiment_statuses[execution_id][0] = RealizationStatus(
        realization_id=0,
        iteration=1,
        status="COMPLETED",
    )

    # Note: We are testing the specific execution status endpoint here
    # Since we didn't register a config, we use a dummy experiment_id
    response = test_client.get(f"/experiments/dummy/executions/{execution_id}/status")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["realization_id"] == 0
    assert data[0]["iteration"] == 1
    assert data[0]["status"] == "COMPLETED"
