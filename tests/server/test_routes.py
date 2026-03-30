from fastapi.testclient import TestClient

from gert.server.gert_server import gert_server_app


def test_create_and_get_experiment() -> None:
    """Test creating an experiment and then retrieving its configuration."""
    client = TestClient(gert_server_app)
    config_data = {
        "name": "test-experiment",
        "base_working_directory": ".",
        "forward_model_steps": [
            {
                "name": "step1",
                "executable": "echo",
                "args": ["hello"],
            },
        ],
        "queue_config": {
            "backend": "local",
        },
        "parameter_matrix": {
            "metadata": {},
            "values": {},
            "datasets": [],
        },
        "observations": [
            {
                "key": {"response": "FOPR"},
                "value": 100.0,
                "std_dev": 10.0,
            },
        ],
    }

    # Test POST /experiments
    response = client.post("/experiments", json=config_data)
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    experiment_id = data["id"]

    # Test GET /experiments/{experiment_id}/config
    response = client.get(f"/experiments/{experiment_id}/config")
    assert response.status_code == 200
    retrieved_config = response.json()
    assert retrieved_config["name"] == "test-experiment"
    assert len(retrieved_config["forward_model_steps"]) == 1
    assert retrieved_config["forward_model_steps"][0]["name"] == "step1"


def test_get_nonexistent_experiment() -> None:
    """Test that retrieving a nonexistent experiment returns 404."""
    client = TestClient(gert_server_app)
    response = client.get("/experiments/nonexistent/config")
    assert response.status_code == 404
    assert response.json()["detail"] == "Experiment 'nonexistent' not found"
