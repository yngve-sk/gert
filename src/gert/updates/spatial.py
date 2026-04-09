"""Spatial toolkit for topological calculations."""

import logging
from typing import Any

import networkx as nx
import numpy as np
import polars as pl
from scipy.spatial.distance import cdist

from gert.experiments.models import GridMetadata

logger = logging.getLogger(__name__)


def gaspari_cohn(dist: np.ndarray, base_length: float) -> Any:  # noqa: ANN401
    """Compute the Gaspari-Cohn taper function.

    Args:
        dist: The distance matrix.
        base_length: The length scale (c = half-width of the function, zero at 2*c).
    """
    r = np.abs(dist) / base_length
    res = np.zeros_like(r)

    idx1 = r <= 1.0
    r1 = r[idx1]
    res[idx1] = (
        1.0 - (5.0 / 3.0) * r1**2 + (5.0 / 8.0) * r1**3 + 0.5 * r1**4 - 0.25 * r1**5
    )

    idx2 = (r > 1.0) & (r < 2.0)
    r2 = r[idx2]
    res[idx2] = (
        4.0
        - 5.0 * r2
        + (5.0 / 3.0) * r2**2
        + (5.0 / 8.0) * r2**3
        - 0.5 * r2**4
        + (1.0 / 12.0) * r2**5
        - 2.0 / (3.0 * r2)
    )

    # Clip numerical noise
    res[res < 1e-12] = 0.0
    return res


def gaussian_taper(dist: np.ndarray, base_length: float) -> Any:  # noqa: ANN401
    """Compute the Gaussian taper function.
    Never truly hits 0, but decays smoothly.
    """
    return np.exp(-0.5 * (dist / base_length) ** 2)


def step_taper(dist: np.ndarray, base_length: float) -> Any:  # noqa: ANN401
    """Compute the Step (Boxcar) taper function.
    1.0 inside base_length, exactly 0.0 outside.
    """
    return np.where(dist <= base_length, 1.0, 0.0)


def spherical_taper(dist: np.ndarray, base_length: float) -> Any:  # noqa: ANN401
    """Compute the Spherical taper function.
    Reaches exactly 0.0 at base_length.
    """
    r = np.abs(dist) / base_length
    res = np.zeros_like(r)
    idx = r <= 1.0
    r_idx = r[idx]
    res[idx] = 1.0 - 1.5 * r_idx + 0.5 * r_idx**3
    return res


class SpatialToolkit:
    # ruff: noqa: SLF001
    """The engine for processing spatial and topological relationships.

    It caches heavy topological graphs (e.g., networkx) once per grid ID
    to avoid redundant compute during update loops.
    """

    def __init__(self) -> None:
        self._grids: dict[str, GridMetadata] = {}
        self._graphs: dict[str, nx.Graph] = {}

    def register_grid(self, grid: GridMetadata) -> None:
        """Register a grid and build its topological graph if not already cached."""
        if grid.id in self._grids:
            return

        self._grids[grid.id] = grid
        self._graphs[grid.id] = self._build_graph(grid)

    def _build_graph(self, grid: GridMetadata) -> nx.Graph:
        """Build a networkx graph for a logical [i, j, k] grid.

        Raises:
            ValueError: If the grid shape has unsupported dimensions (not 1, 2, or 3).
        """
        logger.info(
            f"Building topological graph for grid '{grid.id}' with shape {grid.shape}",
        )

        # For now, we assume a simple 3D lattice based on the shape.
        # In a real implementation, we would also process fault connections here.
        if len(grid.shape) == 1:
            G = nx.path_graph(grid.shape[0])
        elif len(grid.shape) == 2:
            G = nx.grid_2d_graph(grid.shape[0], grid.shape[1])
        elif len(grid.shape) == 3:
            G = nx.grid_graph(
                dim=list(reversed(grid.shape)),
            )  # networkx uses (k, j, i) order for dims
        else:
            msg = (
                f"Unsupported grid dimensions: {len(grid.shape)}. "
                "Only 1D, 2D, and 3D grids are supported."
            )
            raise ValueError(msg)

        return nx.convert_node_labels_to_integers(G)

    def get_grids(self) -> dict[str, GridMetadata]:
        """Returns the dictionary of registered grids."""
        return self._grids

    def get_graph(self, grid_id: str) -> nx.Graph | None:
        """Returns the graph for a given grid_id."""
        return self._graphs.get(grid_id)

    def _get_grid_coordinates(self, grid: GridMetadata) -> Any:  # noqa: ANN401
        if grid._coordinates is not None:
            # Drop purely index/unrelated columns if they exist and return as matrix
            coord_df = grid._coordinates.select(
                pl.col(pl.Float64, pl.Float32, pl.Int64, pl.Int32),
            )
            return coord_df.to_numpy()

        # Fallback to generating integer index coordinates
        shape = grid.shape
        if len(shape) == 1:
            return np.arange(shape[0]).reshape(-1, 1)
        if len(shape) == 2:
            x2, y2 = np.meshgrid(
                np.arange(shape[0]),
                np.arange(shape[1]),
                indexing="ij",
            )
            return np.column_stack([x2.ravel(), y2.ravel()]).astype(float)
        if len(shape) == 3:
            x3, y3, z3 = np.meshgrid(
                np.arange(shape[0]),
                np.arange(shape[1]),
                np.arange(shape[2]),
                indexing="ij",
            )
            return np.column_stack([x3.ravel(), y3.ravel(), z3.ravel()]).astype(float)
        return np.zeros((1, 1))

    def calculate_localization(  # noqa: C901
        self,
        grid_id: str,
        obs_meta: pl.DataFrame,
        base_length: float | list[float] | None = None,
        taper_function: str = "gaspari_cohn",
    ) -> Any:  # noqa: ANN401
        """Calculate topological distances between grid cells and observations.

        Returns a localization matrix of shape (N_params, N_obs) using the
        Gaspari-Cohn taper function if base_length is provided, otherwise None.

        Raises:
            ValueError: If the grid_id is not registered.
        """
        if grid_id not in self._grids:
            msg = f"Grid '{grid_id}' not registered in SpatialToolkit."
            raise ValueError(msg)

        if base_length is None:
            return None
        if isinstance(base_length, float) and base_length <= 0.0:
            return None

        grid = self._grids[grid_id]
        grid_coords = self._get_grid_coordinates(grid)

        # Identify coordinate columns in the observation metadata.
        # This naively attempts to match columns named like the grid coordinates.
        if grid._coordinates is not None:
            coord_cols = grid._coordinates.columns
            # Match only columns present in both
            matched_cols = [c for c in coord_cols if c in obs_meta.columns]
        else:
            # Fallback for implicit grids: check for 'i, j, k' or 'x, y, z' in obs_meta
            fallback_names = [["i", "j", "k"], ["x", "y", "z"]]
            matched_cols = []
            for names in fallback_names:
                candidate_cols = [
                    c for c in names[: len(grid.shape)] if c in obs_meta.columns
                ]
                if len(candidate_cols) == len(grid.shape):
                    matched_cols = candidate_cols
                    break

        if not matched_cols:
            # If we cannot find matching coordinate columns, we cannot localize
            logger.warning(
                f"Could not find matching coordinate columns for grid {grid_id} "
                f"in observation metadata. Available obs columns: {obs_meta.columns}. "
                "Returning unlocalized (rho=1.0) matrix.",
            )
            return np.ones((grid_coords.shape[0], len(obs_meta)))

        obs_coords = obs_meta.select(matched_cols).to_numpy()

        # We need grid_coords to only have the matched dimensions
        if grid._coordinates is not None:
            # Map the matched columns back to their index in the grid_coords matrix
            grid_col_indices = [
                grid._coordinates.columns.index(c) for c in matched_cols
            ]
            grid_coords_matched = grid_coords[:, grid_col_indices]
        else:
            grid_coords_matched = grid_coords

        dist_matrix = cdist(grid_coords_matched, obs_coords, metric="euclidean")

        if isinstance(base_length, list):
            if len(base_length) != grid_coords_matched.shape[1]:
                msg = (
                    f"Anisotropic base_length list {base_length} must match "
                    f"grid dimension {grid_coords_matched.shape[1]}."
                )
                raise ValueError(msg)

            # Scale coordinates to turn the ellipsoid into a sphere of radius 1.0
            scale_arr = np.array(base_length)
            grid_coords_matched /= scale_arr
            obs_coords /= scale_arr

            dist_matrix = cdist(grid_coords_matched, obs_coords, metric="euclidean")
            effective_length = 1.0
        else:
            dist_matrix = cdist(grid_coords_matched, obs_coords, metric="euclidean")
            effective_length = float(base_length)

        # Apply the chosen taper function
        taper_function = taper_function.lower().replace("-", "_")
        if taper_function == "gaussian":
            return gaussian_taper(dist_matrix, effective_length)
        if taper_function == "step":
            return step_taper(dist_matrix, effective_length)
        if taper_function == "spherical":
            return spherical_taper(dist_matrix, effective_length)
        return gaspari_cohn(dist_matrix, effective_length)
