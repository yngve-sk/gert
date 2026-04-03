"""Tests for the monitoring API."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gert.experiments.models import (
    ExecutionState,
    ExperimentConfig,
    ParameterMatrix,
    QueueConfig,
)
from gert.server.gert_server import create_gert_server
from gert.server.router import (
    RealizationStatus,
    ServerState,
    ExecutionData,
)


@pytest.fixture
def test_client() -> TestClient:
    """Fixture to provide a test client for the FastAPI app."""
    app = create_gert_server()
    return TestClient(app)


def test_monitoring_api_get_status(test_client: TestClient) -> None:
    """Test the GET endpoint for experiment status."""
    execution_id = "run_1-test"
    iteration = 1
    realization_id = 0
    server_state = ServerState.get()
    server_state.clear()

    config = ExperimentConfig(
        name="test_exp",
        base_working_directory=".",
        forward_model_steps=[],
        queue_config=QueueConfig(backend="local"),
        parameter_matrix=ParameterMatrix(metadata={}, values={}, datasets=[]),
        updates=[],
        observations=[],
    )
    server_state.configs["test_exp"] = config

    exec_data = ExecutionData(config)
    exec_data.overarching_status = "RUNNING"
    exec_data.statuses[iteration][realization_id] = RealizationStatus(
        realization_id=realization_id,
        iteration=iteration,
        status="COMPLETED",
    )
    server_state.executions[execution_id] = exec_data
    server_state.experiment_executions["test_exp"].append(execution_id)
    server_state.latest_execution_id["test_exp"] = execution_id
    response = test_client.get(f"/experiments/test_exp/executions/{execution_id}/status")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["realization_id"] == 0
    assert data[0]["iteration"] == 1
    assert data[0]["status"] == "COMPLETED"
