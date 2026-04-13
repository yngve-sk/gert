import asyncio
import io
import json
import sys
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from fastapi.testclient import TestClient

from gert.server.gert_server import gert_server_app
from gert.storage.consolidation import ConsolidationWorker


@pytest.mark.asyncio
async def test_end_to_end_local_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Test a full end-to-end local execution loop."""
    monkeypatch.chdir(tmp_path)
    client = TestClient(gert_server_app)

    # 1. Register experiment
    config_data: dict[str, Any] = {
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
    execution_id = res_json["execution_id"]
    iteration = res_json["iteration"]

    # 3. Wait for jobs to finish (local psij is usually fast)
    # We'll check for the workdir creation with a polling loop
    workdir_base = (
        tmp_path / "workdirs" / config_data["name"] / execution_id / f"iter-{iteration}"
    )

    # Poll for workdir_base to be created
    for _ in range(50):
        if workdir_base.exists():
            break
        await asyncio.sleep(0.1)
    assert workdir_base.exists()

    # Check realization 0 and 1 workdirs
    for i in range(2):
        realization_dir = workdir_base / f"realization-{i}"
        # Wait a bit for the job to finish and response.json to be created
        for _ in range(50):
            if (realization_dir / "response.json").exists():
                break
            await asyncio.sleep(0.1)

        assert (realization_dir / "response.json").exists()

        # Now simulate the push that would have happened
        with (realization_dir / "response.json").open() as f:
            payload = json.loads(f.read())
            # Replace placeholder if needed, but dummy FM already has real values
            client.post(
                f"/experiments/{experiment_id}/executions/{execution_id}/ensembles/{iteration}/ingest",
                json=payload,
            )

    ensemble_path = (
        tmp_path
        / "permanent_storage"
        / config_data["name"]
        / execution_id
        / f"iter-{iteration}"
    )
    worker = ConsolidationWorker.get_instance(ensemble_path)
    await worker.consolidate()

    # 4. Verify consolidated data
    response = client.get(
        f"/experiments/{experiment_id}/executions/{execution_id}/ensembles/{iteration}/responses",
    )
    assert response.status_code == 200
    df = pl.read_parquet(io.BytesIO(response.content))
    data = df.to_dicts()
    assert len(data) == 2

    realizations = [item["realization"] for item in data]
    assert set(realizations) == {0, 1}
