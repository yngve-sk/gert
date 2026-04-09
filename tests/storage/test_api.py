"""Tests for the Storage Query API's partitioned schema reading and writing."""

import json
from pathlib import Path

import polars as pl
import pytest

from gert.storage.api import StorageAPI


@pytest.fixture
def storage_path(tmp_path: Path) -> Path:
    """Provide a temporary storage root."""
    return tmp_path / "storage"


@pytest.fixture
def api(storage_path: Path) -> StorageAPI:
    """Provide a StorageAPI instance."""
    return StorageAPI(storage_path)


def test_get_responses_diagonal_concatenation(
    api: StorageAPI,
    storage_path: Path,
) -> None:
    """Prove that get_responses collects disparate schema tables and diagonally
    concatenates them into a massive Tidy DataFrame without dropping columns.
    """
    exp_id = "test_exp"
    exec_id = "run_1"
    iter_nr = 0
    iter_dir = storage_path / exp_id / exec_id / f"iter-{iter_nr}"
    iter_dir.mkdir(parents=True)
    resp_dir = iter_dir / "responses"
    resp_dir.mkdir()

    # 1. Responses from Wells (has well_id, time)
    wells_df = pl.DataFrame(
        {
            "realization": [0, 1],
            "response": ["FOPR", "FOPR"],
            "well_id": ["W1", "W1"],
            "time": [10.0, 10.0],
            "value": [100.0, 200.0],
        },
    )
    wells_df.write_parquet(resp_dir / "wells.parquet")

    # 2. Responses from Global Summary (has field_name, no well_id or time)
    summary_df = pl.DataFrame(
        {
            "realization": [0, 1],
            "response": ["TOTAL_VOL", "TOTAL_VOL"],
            "field_name": ["North", "North"],
            "value": [1e6, 2e6],
        },
    )
    summary_df.write_parquet(resp_dir / "summary.parquet")

    # Execute
    result = api.get_responses(exp_id, exec_id, iter_nr)

    # Assertions
    # It should have 4 rows (2 wells + 2 summaries)
    assert len(result) == 4

    # It should contain the union of all columns
    expected_cols = {
        "realization",
        "response",
        "well_id",
        "time",
        "field_name",
        "value",
    }
    assert set(result.columns) == expected_cols


def test_get_parameters_unrolls_spatial_schemas(
    api: StorageAPI,
    storage_path: Path,
) -> None:
    """Prove that get_parameters groups spatial coordinates into perfectly
    sorted pl.List columns and joins them horizontally with scalar parameters.
    """
    exp_id = "test_params"
    exec_id = "run_1"
    iter_nr = 0
    iter_dir = storage_path / exp_id / exec_id / f"iter-{iter_nr}"
    iter_dir.mkdir(parents=True)
    param_dir = iter_dir / "parameters"
    param_dir.mkdir()

    # 1. Scalar Parameters (1 row per realization)
    scalars_df = pl.DataFrame(
        {
            "realization": [0, 1],
            "fault_mult": [0.5, 0.8],
        },
    )
    scalars_df.write_parquet(param_dir / "scalar.parquet")

    # 2. Spatial Parameters (Multiple rows per realization, e.g., an x/y grid)
    grid_df = pl.DataFrame(
        {
            "realization": [0, 0, 0, 1, 1, 1],
            "x": [2, 0, 1, 1, 2, 0],
            "y": [0, 0, 0, 0, 0, 0],
            "porosity": [0.3, 0.1, 0.2, 0.22, 0.33, 0.11],
        },
    )
    grid_df.write_parquet(param_dir / "grid.parquet")

    # Write registry
    with Path(param_dir / "schemas.json").open("w", encoding="utf-8") as f:
        json.dump(
            {
                "scalar.parquet": {"primary_keys": []},
                "grid.parquet": {"primary_keys": ["x", "y"]},
            },
            f,
        )

    # Execute
    result = api.get_parameters(exp_id, exec_id, iter_nr)

    # Assertions
    assert len(result) == 2
    assert result.filter(pl.col("realization") == 0)["fault_mult"][0] == 0.5

    # Sorted porosities for x=[0, 1, 2] should be [0.1, 0.2, 0.3]
    poro_list_0 = result.filter(pl.col("realization") == 0)["porosity"][0]
    assert list(poro_list_0) == [0.1, 0.2, 0.3]


def test_get_parameters_filtering_and_selection(
    api: StorageAPI,
    storage_path: Path,
) -> None:
    """Prove that get_parameters correctly applies realization filter and column selection."""
    exp_id = "test_params_filter"
    exec_id = "run_1"
    iter_nr = 0
    iter_dir = storage_path / exp_id / exec_id / f"iter-{iter_nr}"
    iter_dir.mkdir(parents=True)
    param_dir = iter_dir / "parameters"
    param_dir.mkdir()

    scalars_df = pl.DataFrame(
        {
            "realization": [0, 1],
            "fault_mult": [0.5, 0.8],
            "permeability": [100.0, 150.0],
        },
    )
    scalars_df.write_parquet(param_dir / "scalar.parquet")

    grid_df = pl.DataFrame(
        {
            "realization": [0, 0, 1, 1],
            "x": [0, 1, 0, 1],
            "porosity": [0.1, 0.2, 0.3, 0.4],
        },
    )
    grid_df.write_parquet(param_dir / "grid.parquet")

    # 1. Filter by realization
    res_realization = api.get_parameters(exp_id, exec_id, iter_nr, realization=1)
    assert len(res_realization) == 1
    assert res_realization["realization"][0] == 1
    assert res_realization["fault_mult"][0] == 0.8
    assert list(res_realization["porosity"][0]) == [0.3, 0.4]

    # 2. Select specific columns
    res_columns = api.get_parameters(exp_id, exec_id, iter_nr, columns=["permeability"])
    assert "realization" in res_columns.columns
    assert "permeability" in res_columns.columns
    assert "fault_mult" not in res_columns.columns
    assert "porosity" not in res_columns.columns

    # 3. Both filter and select on spatial
    res_both = api.get_parameters(
        exp_id,
        exec_id,
        iter_nr,
        columns=["porosity"],
        realization=0,
    )
    assert len(res_both) == 1
    assert "realization" in res_both.columns
    assert "porosity" in res_both.columns
    assert "fault_mult" not in res_both.columns
    assert list(res_both["porosity"][0]) == [0.1, 0.2]


def test_write_parameters_uses_spatial_templates(
    api: StorageAPI,
    storage_path: Path,
) -> None:
    """Prove that write_parameters uses the prior parquet files as templates to explode
    the pl.List columns back into exact spatial coordinates.
    """
    exp_id = "test_write"
    exec_id = "run_1"
    iter_nr = 0
    iter_dir = storage_path / exp_id / exec_id / f"iter-{iter_nr}"
    iter_dir.mkdir(parents=True)
    param_dir = iter_dir / "parameters"
    param_dir.mkdir()

    # 1. Setup the "Prior" template file on disk (A simple 2-cell grid)
    grid_df = pl.DataFrame(
        {
            "realization": [0, 0, 1, 1],
            "i": [0, 1, 0, 1],
            "j": [0, 0, 0, 0],
            "porosity": [0.1, 0.2, 0.15, 0.25],
        },
    )
    grid_df.write_parquet(param_dir / "grid.parquet")

    # 2. Simulate the Math Plugin updating the Wide DataFrame
    updated_wide_df = pl.DataFrame(
        {
            "realization": [0, 1],
            "porosity": [[0.9, 0.99], [0.95, 0.995]],
        },
    )

    # 3. Execute write
    api.write_parameters(exp_id, exec_id, iter_nr, updated_wide_df)

    # 4. Assertions
    written_df = pl.read_parquet(param_dir / "grid.parquet")
    assert len(written_df) == 4
    assert "i" in written_df.columns

    # Realization 0, i=0 should now be 0.9
    val_0_0 = written_df.filter((pl.col("realization") == 0) & (pl.col("i") == 0))[
        "porosity"
    ][0]
    assert val_0_0 == 0.9


def test_get_responses_missing_files_raises_error(
    api: StorageAPI,
    storage_path: Path,
) -> None:
    """If no response files exist for the iteration, it should raise a clear error."""
    with pytest.raises(
        FileNotFoundError,
        match="Consolidated responses for experiment",
    ):
        api.get_responses("missing_exp", "run_0", 0)


def test_get_parameters_missing_files_raises_error(
    api: StorageAPI,
    storage_path: Path,
) -> None:
    """If no parameter files exist for the iteration, it should raise a clear error."""
    with pytest.raises(FileNotFoundError, match=r"Parameters not found\."):
        api.get_parameters("missing_exp", "run_0", 0)
