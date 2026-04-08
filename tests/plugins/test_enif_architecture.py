"""Unit tests for the EnIFUpdate architectural plumbing (Parameters, Grids, Metadata)."""

import collections
from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import polars as pl
import pytest
import scipy.sparse as sp

from gert.experiments.models import ParameterMetadata
from gert.plugins.enif_update import EnIFUpdate
from gert.updates.spatial import SpatialToolkit


@pytest.fixture
def enif() -> EnIFUpdate:
    """Provide a fresh instance of the EnIFUpdate plugin."""
    return EnIFUpdate()


@pytest.fixture
def mock_toolkit() -> MagicMock:
    """Provide a mocked SpatialToolkit."""
    toolkit = MagicMock(spec=SpatialToolkit)
    toolkit.calculate_localization.return_value = None

    # We provide a dummy graph object for any requested grid_id
    class DummyDict(collections.UserDict[str, Any]):
        def get(self, key: str, default: Any = None) -> Any:
            return "dummy_graph"

    toolkit._graphs = DummyDict()
    return toolkit


@pytest.fixture(autouse=True)
def mock_math_layer() -> Generator[None]:
    with (
        patch("gert.plugins.enif_update.linear_boost_ic_regression") as mock_lbr,
        patch("gert.plugins.enif_update.EnIF") as mock_enif,
        patch(
            "gert.plugins.enif_update.fit_precision_cholesky_approximate",
        ) as mock_fit,
    ):
        mock_lbr.return_value = np.zeros((2, 2))  # dummy H
        mock_enif_instance = mock_enif.return_value
        mock_enif_instance.transport.side_effect = lambda U, **_kwargs: (
            U
        )  # Return unchanged U

        # Return an identity sparse matrix of the correct shape
        mock_fit.side_effect = lambda X, _graph, **_kwargs: sp.diags(
            [np.ones(X.shape[1])],
            offsets=[0],
            format="csc",
        )

        yield


def test_scalar_parameter_bypasses_localization(
    enif: EnIFUpdate,
    mock_toolkit: MagicMock,
) -> None:
    """Scalars should not trigger spatial localization."""
    # Setup
    n_reals = 10
    parameters = pl.DataFrame(
        {
            "realization": np.arange(n_reals),
            "SCALAR_A": np.random.normal(size=n_reals),
            "SCALAR_B": np.random.normal(size=n_reals),
        },
    )

    metadata = [
        ParameterMetadata(name="SCALAR_A", columns=["SCALAR_A"], grid_id=None),
        ParameterMetadata(name="SCALAR_B", columns=["SCALAR_B"], grid_id=None),
    ]

    observations = pl.DataFrame(
        {
            "response": ["OBS"],
            "value": [1.0],
            "std_dev": [0.1],
        },
    )
    responses = pl.DataFrame(
        {
            "realization": np.arange(n_reals),
            "response": ["OBS"] * n_reals,
            "value": np.random.normal(size=n_reals),
        },
    )

    # Execute
    result = enif.perform_update(
        parameters,
        metadata,
        responses,
        observations,
        mock_toolkit,
        {},
    )

    # Verify
    mock_toolkit.calculate_localization.assert_not_called()
    assert result.shape == parameters.shape


def test_2d_grid_parameter_triggers_localization(
    enif: EnIFUpdate,
    mock_toolkit: MagicMock,
) -> None:
    """2D grid parameters should query the toolkit using their grid_id."""
    # Setup
    n_reals = 5
    nx, ny = 10, 10
    n_cells = nx * ny
    columns = [f"PERM_2D_{i}" for i in range(n_cells)]

    data = {"realization": np.arange(n_reals)}
    for col in columns:
        data[col] = np.random.normal(size=n_reals)

    parameters = pl.DataFrame(data)

    metadata = [
        ParameterMetadata(name="PERM_2D", columns=columns, grid_id="grid_2d"),
    ]

    observations = pl.DataFrame(
        {
            "response": ["OBS"],
            "value": [1.0],
            "std_dev": [0.1],
        },
    )
    responses = pl.DataFrame(
        {
            "realization": np.arange(n_reals),
            "response": ["OBS"] * n_reals,
            "value": np.random.normal(size=n_reals),
        },
    )

    # Execute
    result = enif.perform_update(
        parameters,
        metadata,
        responses,
        observations,
        mock_toolkit,
        {},
    )

    # Verify
    mock_toolkit.calculate_localization.assert_called_once_with(
        grid_id="grid_2d",
        obs_meta=observations,
    )
    assert result.shape == parameters.shape


def test_3d_grid_parameter_triggers_localization(
    enif: EnIFUpdate,
    mock_toolkit: MagicMock,
) -> None:
    """3D grid parameters should query the toolkit using their grid_id."""
    # Setup
    n_reals = 2
    nx, ny, nz = 5, 5, 2
    n_cells = nx * ny * nz
    columns = [f"PORO_3D_{i}" for i in range(n_cells)]

    data = {"realization": np.arange(n_reals)}
    for col in columns:
        data[col] = np.random.normal(size=n_reals)

    parameters = pl.DataFrame(data)

    metadata = [
        ParameterMetadata(name="PORO_3D", columns=columns, grid_id="grid_3d"),
    ]

    observations = pl.DataFrame(
        {
            "response": ["OBS"],
            "value": [1.0],
            "std_dev": [0.1],
        },
    )
    responses = pl.DataFrame(
        {
            "realization": np.arange(n_reals),
            "response": ["OBS"] * n_reals,
            "value": np.random.normal(size=n_reals),
        },
    )

    # Execute
    result = enif.perform_update(
        parameters,
        metadata,
        responses,
        observations,
        mock_toolkit,
        {},
    )

    # Verify
    mock_toolkit.calculate_localization.assert_called_once_with(
        grid_id="grid_3d",
        obs_meta=observations,
    )
    assert result.shape == parameters.shape


def test_mixed_parameters_routing(
    enif: EnIFUpdate,
    mock_toolkit: MagicMock,
) -> None:
    """A mix of scalars and grids should route to the toolkit correctly."""
    # Setup
    n_reals = 3

    # Scalar
    scalar_cols = ["FAULT_MULT"]
    # 2D
    nx, ny = 5, 5
    grid_2d_cols = [f"NTG_{i}" for i in range(nx * ny)]
    # 3D
    nx, ny, nz = 5, 5, 5
    grid_3d_cols = [f"PERM_{i}" for i in range(nx * ny * nz)]

    all_cols = scalar_cols + grid_2d_cols + grid_3d_cols
    data = {"realization": np.arange(n_reals)}
    for col in all_cols:
        data[col] = np.random.normal(size=n_reals)

    parameters = pl.DataFrame(data)

    metadata = [
        ParameterMetadata(name="FAULT_MULT", columns=scalar_cols, grid_id=None),
        ParameterMetadata(name="NTG", columns=grid_2d_cols, grid_id="top_layer_2d"),
        ParameterMetadata(name="PERM", columns=grid_3d_cols, grid_id="main_res_3d"),
    ]

    observations = pl.DataFrame(
        {
            "response": ["OBS"],
            "value": [1.0],
            "std_dev": [0.1],
        },
    )
    responses = pl.DataFrame(
        {
            "realization": np.arange(n_reals),
            "response": ["OBS"] * n_reals,
            "value": np.random.normal(size=n_reals),
        },
    )

    # Execute
    result = enif.perform_update(
        parameters,
        metadata,
        responses,
        observations,
        mock_toolkit,
        {},
    )

    # Verify
    assert mock_toolkit.calculate_localization.call_count == 2

    # Order of calls should match metadata list (skipping the scalar)
    calls = mock_toolkit.calculate_localization.call_args_list
    assert calls[0].kwargs["grid_id"] == "top_layer_2d"
    assert calls[1].kwargs["grid_id"] == "main_res_3d"
    assert result.shape == parameters.shape
