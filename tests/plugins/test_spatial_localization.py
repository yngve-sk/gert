import numpy as np
import polars as pl

from gert.experiments.models import GridMetadata
from gert.updates.spatial import SpatialToolkit, gaspari_cohn


def test_gaspari_cohn() -> None:
    dist = np.array([0.0, 0.5, 1.0, 1.5, 2.0, 2.5])
    res = gaspari_cohn(dist, base_length=1.0)

    assert res[0] == 1.0  # distance 0 -> 1.0
    assert 0.0 < res[1] < 1.0
    assert 0.0 < res[2] < 1.0  # r=1.0 is > 0 in gaspari_cohn
    assert 0.0 < res[3] < res[2]
    assert res[4] == 0.0  # r=2.0 -> 0.0
    assert res[5] == 0.0  # r>2.0 -> 0.0


def test_spatial_toolkit_localization() -> None:
    toolkit = SpatialToolkit()
    grid = GridMetadata(
        id="test_grid",
        shape=(2, 2),
        _coordinates=pl.DataFrame(
            {
                "x": [0.0, 1.0, 0.0, 1.0],
                "y": [0.0, 0.0, 1.0, 1.0],
            },
        ),
    )
    toolkit.register_grid(grid)

    obs_df = pl.DataFrame(
        {
            "value": [10.0],
            "std_dev": [1.0],
            "x": [0.0],
            "y": [0.0],
        },
    )

    rho = toolkit.calculate_localization("test_grid", obs_df, base_length=1.0)

    assert rho is not None
    assert rho.shape == (4, 1)

    # Node 0 is at (0,0) -> dist=0
    assert rho[0, 0] == 1.0

    # Node 1 is at (1,0) -> dist=1
    assert 0.0 < rho[1, 0] < 1.0

    # Node 2 is at (0,1) -> dist=1
    assert 0.0 < rho[2, 0] < 1.0

    # Node 3 is at (1,1) -> dist=sqrt(2) = 1.414, which is < 2.0
    assert 0.0 < rho[3, 0] < 1.0

    assert rho[3, 0] < rho[1, 0]


def test_spatial_toolkit_implicit_grid() -> None:
    toolkit = SpatialToolkit()
    # implicit 1D grid, length 5
    grid = GridMetadata(id="grid1d", shape=(5,))
    toolkit.register_grid(grid)

    # Note: implicit grid uses "i" for 1D, or x for 1D? It uses the first column if available,
    # but the fallback looks for ['i', 'j', 'k'] or ['x', 'y', 'z'].
    # The grid coordinates generated are 0, 1, 2, 3, 4.
    obs_df = pl.DataFrame(
        {
            "value": [10.0],
            "std_dev": [1.0],
            "i": [2.0],  # center of grid
        },
    )

    rho = toolkit.calculate_localization("grid1d", obs_df, base_length=1.0)

    assert rho is not None
    assert rho.shape == (5, 1)
    assert rho[2, 0] == 1.0
    assert rho[0, 0] == 0.0  # dist 2, base_length 1 -> r=2 -> 0.0
    assert rho[4, 0] == 0.0
