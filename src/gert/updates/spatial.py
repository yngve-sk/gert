"""Spatial toolkit for topological calculations."""

import logging

import networkx as nx
import polars as pl

from gert.experiments.models import GridMetadata

logger = logging.getLogger(__name__)


class SpatialToolkit:
    """The engine for processing spatial and topological relationships.

    It caches heavy topological graphs (e.g., networkx) once per grid ID
    to avoid redundant compute during update loops.
    """

    def __init__(self) -> None:
        self._grids: dict[str, GridMetadata] = {}
        self._graphs: dict[str, nx.Graph] = {}

    def register_grid(self, grid: GridMetadata) -> None:
        """Register a grid and build its topological graph if not already cached."""
        if grid.id in self._graphs:
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

    def calculate_localization(
        self,
        grid_id: str,
        obs_meta: pl.DataFrame,
    ) -> None:
        """Calculate topological distances between grid cells and observations.

        STUB: Currently returns None as per requirement.

        Raises:
            ValueError: If the grid_id is not registered.
        """
        if grid_id not in self._graphs:
            msg = f"Grid '{grid_id}' not registered in SpatialToolkit."
            raise ValueError(msg)

        # In a real implementation, this would return a distance or weight matrix.
