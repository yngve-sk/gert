import logging
import operator
import time
from unittest.mock import patch

from fastapi.testclient import TestClient

from gert.server.router import ServerState

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_deterministic_api(client: TestClient) -> None:
    config_data = {
        "name": "deterministic-test",
        "base_working_directory": ".",
        "forward_model_steps": [
            {
                "name": "dummy_step",
                "executable": "/bin/echo",
                "args": ["hello"],
            },
        ],
        "queue_config": {
            "backend": "local",
        },
        "parameter_matrix": {
            "metadata": {},
            "values": {
                "PARAM": {0: 1.0, 1: 2.0},
            },
            "datasets": [],
        },
        "observations": [],
    }

    with patch(
        "gert.experiment_runner.job_submitter.JobSubmitter.submit",
        return_value="mock_job_id",
    ):
        logger.info("Registering experiment...")
        resp = client.post("/api/experiments", json=config_data)
        assert resp.status_code == 201
        experiment_id = resp.json()["id"]
        logger.info(f"Registered experiment: {experiment_id}")

        logger.info("Starting experiment...")
        resp = client.post(f"/api/experiments/{experiment_id}/start")
        assert resp.status_code == 200
        start_data = resp.json()
        execution_id = start_data["execution_id"]
        logger.info(f"Started execution: {execution_id}")

        logger.info("Fetching config...")
        resp = client.get(f"/api/experiments/{experiment_id}/config")
        assert resp.status_code == 200
        config = resp.json()
        logger.info(f"Config JSON keys: {list(config.keys())}")

        logger.info("Injecting mock statuses to avoid waiting for jobs...")
        client.post(
            f"/api/experiments/{experiment_id}/executions/{execution_id}/ensembles/0/realizations/0/status?status=RUNNING",
        )
        client.post(
            f"/api/experiments/{experiment_id}/executions/{execution_id}/ensembles/0/realizations/0/status?status=RUNNING&step_name=dummy_step",
        )
        client.post(
            f"/api/experiments/{experiment_id}/executions/{execution_id}/ensembles/0/realizations/0/status?status=COMPLETED&step_name=dummy_step",
        )
        client.post(
            f"/api/experiments/{experiment_id}/executions/{execution_id}/ensembles/0/realizations/0/status?status=COMPLETED",
        )

        logger.info("Fetching status...")
        resp = client.get(
            f"/api/experiments/{experiment_id}/executions/{execution_id}/status",
        )
        assert resp.status_code == 200
        statuses = resp.json()
        logger.info(f"Number of statuses: {len(statuses)}")
        assert len(statuses) > 0, "Statuses should not be empty!"
        logger.info(f"Sample status: {statuses[0]}")

        logger.info("Simulating server restart (clearing in-memory state)...")

        server_state = ServerState.get()

        # Stop orchestrator
        if execution_id in server_state.executions:
            exec_data = server_state.executions[execution_id]
            if exec_data.orchestrator:
                exec_data.orchestrator.pause(force=True)

        # Give it a moment to cancel
        time.sleep(0.5)

        server_state.clear()

        logger.info("Fetching statuses after restart...")
        resp = client.get(
            f"/api/experiments/{experiment_id}/executions/{execution_id}/status",
        )
        assert resp.status_code == 200
        recovered_statuses = resp.json()
        logger.info(f"Number of recovered statuses: {len(recovered_statuses)}")
        assert len(recovered_statuses) == len(statuses), (
            f"Mismatch! Original: {statuses}, Recovered: {recovered_statuses}"
        )

        # Sort for deterministic comparison using operator.itemgetter
        sort_key = operator.itemgetter("iteration", "realization_id")
        statuses.sort(key=sort_key)
        recovered_statuses.sort(key=sort_key)

        logger.info(f"Original status 0: {statuses[0]}")
        logger.info(f"Recovered status 0: {recovered_statuses[0]}")

        assert statuses[0]["status"] == recovered_statuses[0]["status"]
        assert len(statuses[0]["steps"]) == len(recovered_statuses[0]["steps"])
        assert (
            statuses[0]["steps"][0]["status"]
            == recovered_statuses[0]["steps"][0]["status"]
        )

        logger.info("Deterministic recovery successful!")
