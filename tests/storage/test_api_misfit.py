"""Unit tests specifically verifying the math of misfit calculations in the Storage API."""

import json
from pathlib import Path
from unittest.mock import patch

import polars as pl
import pytest

from gert.storage.api import StorageAPI


@pytest.fixture
def mock_storage(tmp_path: Path) -> tuple[Path, str, str, int]:
    """Provide a mocked minimal storage directory structure."""
    exp_id = "test_exp"
    exec_id = "test_exec"
    iter_nr = 0
    iter_dir = tmp_path / exp_id / exec_id / f"iter-{iter_nr}"
    iter_dir.mkdir(parents=True)
    return tmp_path, exp_id, exec_id, iter_nr


def test_misfit_math_correctness(mock_storage: tuple[Path, str, str, int]) -> None:
    """Test that the signed chi-squared and absolute misfits are calculated correctly."""
    tmp_path, exp_id, exec_id, iter_nr = mock_storage
    api = StorageAPI(tmp_path)

    config_data = {
        "name": exp_id,
        "base_working_directory": str(tmp_path),
        "forward_model_steps": [],
        "queue_config": {},
        "parameter_matrix": {"values": {}},
        "observations": [
            {"key": {"response": "POS_ERR"}, "value": 10.0, "std_dev": 2.0},
            {"key": {"response": "NEG_ERR"}, "value": -5.0, "std_dev": 1.0},
            {"key": {"response": "PERFECT"}, "value": 0.0, "std_dev": 5.0},
            {"key": {"response": "FRACTION"}, "value": 100.0, "std_dev": 10.0},
        ],
        "updates": [],
    }
    (tmp_path / exp_id / "config.json").write_text(json.dumps(config_data))

    # Mock responses for a single realization
    sim_responses = pl.DataFrame(
        {
            "realization": [0, 0, 0, 0],
            "response": ["POS_ERR", "NEG_ERR", "PERFECT", "FRACTION"],
            "value": [
                14.0,  # obs=10, std=2 -> res=4, norm=2 -> misfit=4, abs=2
                -8.0,  # obs=-5, std=1 -> res=-3, norm=-3 -> misfit=-9, abs=3
                0.0,  # obs=0, std=5 -> res=0, norm=0 -> misfit=0, abs=0
                95.0,  # obs=100, std=10 -> res=-5, norm=-0.5 -> misfit=-0.25, abs=0.5
            ],
        },
    )

    with patch.object(api, "get_responses", return_value=sim_responses):
        summary = api.get_observation_summary(exp_id, exec_id, iter_nr)

    assert summary is not None

    # Verification
    details = {str(d.response): d for d in summary.details}

    # POS_ERR
    assert details["POS_ERR"].absolute_residual == 4.0
    assert details["POS_ERR"].misfit == 4.0
    assert details["POS_ERR"].absolute_misfit == 2.0

    # NEG_ERR
    assert details["NEG_ERR"].absolute_residual == 3.0
    assert details["NEG_ERR"].misfit == -9.0
    assert details["NEG_ERR"].absolute_misfit == 3.0

    # PERFECT
    assert details["PERFECT"].absolute_residual == 0.0
    assert details["PERFECT"].misfit == 0.0
    assert details["PERFECT"].absolute_misfit == 0.0

    # FRACTION
    assert details["FRACTION"].absolute_residual == 5.0
    assert details["FRACTION"].misfit == -0.25
    assert details["FRACTION"].absolute_misfit == 0.5

    # Check averages
    expected_avg_abs_res = (4.0 + 3.0 + 0.0 + 5.0) / 4.0
    expected_avg_misfit = (4.0 - 9.0 + 0.0 - 0.25) / 4.0
    expected_avg_abs_misfit = (2.0 + 3.0 + 0.0 + 0.5) / 4.0

    assert summary.average_absolute_residual == pytest.approx(expected_avg_abs_res)
    assert summary.average_misfit == pytest.approx(expected_avg_misfit)
    assert summary.average_absolute_misfit == pytest.approx(expected_avg_abs_misfit)


def test_misfit_multiple_realizations_averaging(
    mock_storage: tuple[Path, str, str, int],
) -> None:
    """Test that misfits are properly averaged across an ensemble of realizations."""
    tmp_path, exp_id, exec_id, iter_nr = mock_storage
    api = StorageAPI(tmp_path)

    config_data = {
        "name": exp_id,
        "base_working_directory": str(tmp_path),
        "forward_model_steps": [],
        "queue_config": {},
        "parameter_matrix": {"values": {}},
        "observations": [
            {"key": {"response": "WELL_A"}, "value": 100.0, "std_dev": 10.0},
        ],
        "updates": [],
    }
    (tmp_path / exp_id / "config.json").write_text(json.dumps(config_data))

    # Realization 0: value 120 -> res 20 -> norm 2 -> misfit 4, abs 2
    # Realization 1: value  80 -> res -20 -> norm -2 -> misfit -4, abs 2
    # Realization 2: value 100 -> res 0 -> norm 0 -> misfit 0, abs 0
    sim_responses = pl.DataFrame(
        {
            "realization": [0, 1, 2],
            "response": ["WELL_A", "WELL_A", "WELL_A"],
            "value": [120.0, 80.0, 100.0],
        },
    )

    with patch.object(api, "get_responses", return_value=sim_responses):
        summary = api.get_observation_summary(exp_id, exec_id, iter_nr)

    assert summary is not None

    # Averages for WELL_A specifically
    details = {str(d.response): d for d in summary.details}
    well_a = details["WELL_A"]

    assert well_a.absolute_residual == pytest.approx((20.0 + 20.0 + 0.0) / 3.0)
    # The misfits should average to exactly 0 due to symmetric spread around truth
    assert well_a.misfit == pytest.approx((4.0 - 4.0 + 0.0) / 3.0)
    assert well_a.absolute_misfit == pytest.approx((2.0 + 2.0 + 0.0) / 3.0)

    # Global averages (same since only one observation)
    assert summary.average_absolute_residual == well_a.absolute_residual
    assert summary.average_misfit == well_a.misfit
    assert summary.average_absolute_misfit == well_a.absolute_misfit
