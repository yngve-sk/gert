import numpy as np
import polars as pl

from gert.experiments.models import GridMetadata
from gert.updates.spatial import (
    SpatialToolkit,
    gaussian_taper,
    spherical_taper,
    step_taper,
)


def test_gaussian_taper() -> None:
    dist = np.array([0.0, 1.0, 2.0, 5.0])
    res = gaussian_taper(dist, base_length=2.0)
    assert res[0] == 1.0
    assert 0.0 < res[1] < 1.0
    assert 0.0 < res[2] < res[1]
    assert res[3] > 0.0  # Gaussian never hits absolute zero


def test_step_taper() -> None:
    dist = np.array([0.0, 0.99, 1.0, 1.01, 2.0])
    res = step_taper(dist, base_length=1.0)
    np.testing.assert_array_equal(res, [1.0, 1.0, 1.0, 0.0, 0.0])


def test_spherical_taper() -> None:
    dist = np.array([0.0, 0.5, 1.0, 1.5])
    res = spherical_taper(dist, base_length=1.0)
    assert res[0] == 1.0
    assert 0.0 < res[1] < 1.0
    assert res[2] == 0.0
    assert res[3] == 0.0


def test_anisotropic_localization() -> None:
    toolkit = SpatialToolkit()

    grid = GridMetadata(
        id="test_grid",
        shape=(1, 2),
        _coordinates=pl.DataFrame({"x": [0.0, 10.0], "y": [0.0, 0.0]}),
    )
    toolkit.register_grid(grid)

    obs_df = pl.DataFrame(
        {
            "value": [10.0, 20.0],
            "std_dev": [1.0, 1.0],
            "x": [10.0, 0.0],
            "y": [0.0, 1.0],
        },
    )

    # We pass base_length=[10.0, 1.0].
    # Distance from grid(0,0) to obs1(10,0) without anisotropy is 10.0. With [10, 1], it becomes 1.0.
    # Distance from grid(0,0) to obs2(0,1) without anisotropy is 1.0. With [10, 1], it is 1.0.
    # So both should have the exact same taper output for grid node 0.
    rho = toolkit.calculate_localization(
        "test_grid",
        obs_df,
        base_length=[10.0, 1.0],
        taper_function="step",
    )

    # Node 0 to Obs 1 scaled dist: (10-0)/10 = 1, (0-0)/1 = 0. -> dist=1.0 -> step is 1.0
    assert rho is not None
    assert rho[0, 0] == 1.0
    # Node 0 to Obs 2 scaled dist: (0-0)/10 = 0, (1-0)/1 = 1. -> dist=1.0 -> step is 1.0
    assert rho[0, 1] == 1.0
