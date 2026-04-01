import json
import typing
from pathlib import Path

import polars as pl
import pytest

from gert.storage.api import StorageAPI


@pytest.fixture
def storage_path(tmp_path: Path) -> Path:
    return tmp_path / "storage"


@pytest.fixture
def api(storage_path: Path) -> StorageAPI:
    return StorageAPI(storage_path)


def test_get_observation_summary_calculates_and_caches(
    api: StorageAPI,
    storage_path: Path,
) -> None:
    exp_id = "test_exp"
    exec_id = "run_1"
    iter_nr = 0
    exp_dir = storage_path / exp_id
    exp_dir.mkdir(parents=True)
    config = {
        "name": exp_id,
        "base_working_directory": str(exp_dir),
        "forward_model_steps": [],
        "queue_config": {},
        "parameter_matrix": {"values": {}},
        "observations": [
            {"key": {"response": "FOPR"}, "value": 150.0, "std_dev": 10.0},
            {"key": {"response": "TOTAL_VOL"}, "value": 2e6, "std_dev": 1e5},
        ],
        "updates": [],
    }
    (exp_dir / "config.json").write_text(json.dumps(config))
    exec_dir = exp_dir / exec_id
    exec_dir.mkdir()
    state = {
        "experiment_id": exp_id,
        "execution_id": exec_id,
        "status": "COMPLETED",
        "current_iteration": 1,
    }
    (exec_dir / "execution_state.json").write_text(json.dumps(state))
    iter_dir = exec_dir / f"iter-{iter_nr}"
    iter_dir.mkdir()
    resp_dir = iter_dir / "responses"
    resp_dir.mkdir()
    resp_df = pl.DataFrame(
        {
            "realization": [0, 1, 0, 1],
            "response": ["FOPR", "FOPR", "TOTAL_VOL", "TOTAL_VOL"],
            "value": [100.0, 200.0, 1.8e6, 2.2e6],
        },
    )
    resp_df.write_parquet(resp_dir / "data.parquet")
    (resp_dir / "schemas.json").write_text(
        json.dumps(
            {
                "data.parquet": {"primary_keys": ["response"]},
            },
        ),
    )
    result = api.get_observation_summary(exp_id, exec_id, iter_nr)
    assert result is not None
    assert result.average_normalized_misfit is not None
    assert result.average_absolute_residual is not None
    assert result.average_absolute_misfit is not None
    assert result.details is not None

    # normalized residual = normal_misfit / max_abs(normal_misfit)
    # FOPR real 0 normal_misfit: (100-150)/10 = -5
    # FOPR real 1 normal_misfit: (200-150)/10 = 5
    # TOT real 0 normal_misfit: (1.8e6-2e6)/1e5 = -2
    # TOT real 1 normal_misfit: (2.2e6-2e6)/1e5 = 2
    # Overall max abs = 5.
    # FOPR 0: -5 / 5 = -1.0
    # FOPR 1: 5 / 5 = 1.0
    # TOT 0: -2 / 5 = -0.4
    # TOT 1: 2 / 5 = 0.4
    # Mean of normalized residuals is exactly 0.0 because of the symmetry
    assert abs(result.average_normalized_misfit - 0.0) < 1e-6

    details = result.details
    assert len(details) == 2
    for d in details:
        if d.response == "FOPR":
            assert abs(d.absolute_residual - 50.0) < 1e-6
            # Average normalized residual for FOPR is (-1.0 + 1.0)/2 = 0
            assert abs(d.normalized_misfit - 0.0) < 1e-6
            assert abs(d.absolute_misfit - 5.0) < 1e-6
        elif d.response == "TOTAL_VOL":
            assert abs(d.absolute_residual - 200000.0) < 1e-6
            # Average normalized residual for TOT is (-0.4 + 0.4)/2 = 0
            assert abs(d.normalized_misfit - 0.0) < 1e-6
            assert abs(d.absolute_misfit - 2.0) < 1e-6

    cache_file = iter_dir / "observation_summary.json"
    assert cache_file.exists()

    cached_data = typing.cast(
        "dict[str, typing.Any]",
        json.loads(cache_file.read_text()),
    )
    assert abs(cached_data["average_normalized_misfit"] - 0.0) < 1e-6
