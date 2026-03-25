import asyncio
import json
import shutil
import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gert.server.gert_server import gert_server_app
from gert.storage.consolidation import ConsolidationWorker


@pytest.fixture
def clean_storage() -> Generator[None, None, None]:
    """Fixture to clean up the storage directory."""
    for path in [Path("./gert_storage"), Path("./workdirs")]:
        if path.exists():
            shutil.rmtree(path)
    yield
    for path in [Path("./gert_storage"), Path("./workdirs")]:
        if path.exists():
            shutil.rmtree(path)


@pytest.mark.asyncio
async def test_end_to_end_local_run(clean_storage: None) -> None:
    """Test a full end-to-end local execution loop."""
    client = TestClient(gert_server_app)

    # 1. Register experiment
    config_data = {
        "name": "e2e-test",
        "base_working_directory": ".",
        "forward_model_steps": [
            {
                "name": "dummy_fm",
                "executable": sys.executable,
                "args": [
                    "-c",
                    (
                        '"import json; '
                        "payload = {"
                        '\\"realization\\": {realization}, '
                        '\\"source_step\\": \\"dummy_step\\", '
                        '\\"key\\": {\\"response\\": \\"FOPR\\"}, '
                        '\\"value\\": float(100 + {realization})'
                        "}; "
                        'open(\\"response.json\\", \\"w\\").write(json.dumps(payload))"'
                    ),
                ],
            },
        ],
        "queue_config": {
            "backend": "local",
            "custom_attributes": {},
        },
        "parameter_matrix": {
            "metadata": {"MULTFLT": {"source": "prior", "updatable": True}},
            "values": {"MULTFLT": {0: 1.0, 1: 2.0}},
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

    response = client.post("/experiments", json=config_data)
    assert response.status_code == 201
    experiment_id = response.json()["id"]

    # 2. Start experiment
    # Note: Currently start_experiment is synchronous and runs everything immediately.
    # In a real app it would be a background task.
    # Also, the dummy FM writes to 'response.json' in its workdir.
    response = client.post(f"/experiments/{experiment_id}/start")
    assert response.status_code == 200
    res_json = response.json()
    execution_id = res_json["experiment_id"]
    ensemble_id = res_json["ensemble_id"]

    # 3. Wait for jobs to finish (local psij is usually fast)
    # We'll check for the workdir creation
    workdir_base = (
        Path("./gert_storage/workdirs").resolve() / execution_id / ensemble_id
    )
    assert workdir_base.exists()
    # Check realization 0 and 1 workdirs
    for i in range(2):
        realization_dir = workdir_base / f"realization-{i}"
        # Wait a bit for the job to finish
        for _ in range(20):
            if (realization_dir / "response.json").exists():
                break
            await asyncio.sleep(0.1)

        assert (realization_dir / "response.json").exists()

        # Now simulate the push that would have happened
        with (realization_dir / "response.json").open() as f:
            payload = json.loads(f.read())
            # Replace placeholder if needed, but dummy FM already has real values
            client.post(
                f"/storage/{execution_id}/ensembles/{ensemble_id}/ingest",
                json=payload,
            )

    worker = ConsolidationWorker(Path("./gert_storage"))
    worker.consolidate(execution_id)

    # 4. Verify consolidated data
    response = client.get(f"/storage/{execution_id}/ensembles/{ensemble_id}/responses")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2

    realizations = [item["realization"] for item in data]
    assert set(realizations) == {0, 1}
