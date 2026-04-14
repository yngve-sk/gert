from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient

from gert.__main__ import _scan_for_configs
from gert.server.gert_server import create_gert_server


def test_scan_and_start_experiment(
    copy_example: Callable[[str], Path],
    client: TestClient,
) -> None:
    """Verify that scanned configurations can be registered and started successfully."""
    # 1. Scan for configurations (which now correctly injects base_working_directory)
    config_dir = copy_example("many_steps_many_iterations")
    configs = _scan_for_configs([config_dir])

    assert len(configs) > 0, "Should have found at least one configuration"

    exp_id, config = next(iter(configs.items()))

    # Verify the generated ID uses an underscore, not a slash, to avoid routing issues
    assert "/" not in exp_id
    assert exp_id == "many-steps-many-iterations"

    # 2. Start the server
    app = create_gert_server()

    # 3. Register the experiment explicitly (simulating what `gert ui` does)
    response = client.post(
        "/api/experiments",
        params={"id": exp_id},
        content=config.model_dump_json(),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 201

    # 4. Start the execution (simulating what the Svelte GUI "New Run" button does)
    # This previously failed with a 500 error due to missing base_working_directory
    response = client.post(f"/api/experiments/{exp_id}/start")
    assert response.status_code == 200, (
        f"Expected 200 OK, got {response.status_code}: {response.text}"
    )

    data = response.json()
    assert "execution_id" in data
