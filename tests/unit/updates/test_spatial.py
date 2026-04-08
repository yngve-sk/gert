"""Unit tests for the spatial mapping and topological graph generation."""

import networkx as nx
import pytest

from gert.experiments.models import GridMetadata
from gert.updates.spatial import SpatialToolkit


@pytest.fixture
def toolkit() -> SpatialToolkit:
    """Provide a fresh SpatialToolkit instance."""
    return SpatialToolkit()


def test_1d_grid_mapping(toolkit: SpatialToolkit) -> None:
    """Test that a 1D grid is correctly mapped to a path graph."""
    # 1D array of 3 elements: [0, 1, 2]
    grid = GridMetadata(id="grid_1d", shape=(3,))
    graph = toolkit._build_graph(grid)
    data = nx.node_link_data(graph)

    assert isinstance(graph, nx.Graph)
    assert len(data["nodes"]) == 3
    assert len(data["edges"]) == 2

    # Nodes should be 0, 1, 2
    assert [n["id"] for n in data["nodes"]] == [0, 1, 2]

    # Edges should be (0, 1) and (1, 2)
    # Undirected graphs can return edges in either order, so we sort them
    edges = {tuple(sorted((e["source"], e["target"]))) for e in data["edges"]}
    assert edges == {(0, 1), (1, 2)}
    assert (0, 2) not in edges


def test_2d_grid_mapping(toolkit: SpatialToolkit) -> None:
    """Test that a 2D grid is correctly mapped to a 2D grid graph."""
    # 2D array of shape (2, 3):
    # 0  1  2
    # 3  4  5
    grid = GridMetadata(id="grid_2d", shape=(2, 3))
    graph = toolkit._build_graph(grid)
    data = nx.node_link_data(graph)

    assert isinstance(graph, nx.Graph)
    assert len(data["nodes"]) == 6
    # Edges: 2 per row (4 total), 3 per column (3 total) = 7
    assert len(data["edges"]) == 7

    # Verify nodes are correctly flattened into integers
    assert [n["id"] for n in data["nodes"]] == list(range(6))

    edges = {tuple(sorted((e["source"], e["target"]))) for e in data["edges"]}

    expected_edges = {
        (0, 1),
        (1, 2),
        (3, 4),
        (4, 5),  # horizontal
        (0, 3),
        (1, 4),
        (2, 5),  # vertical
    }
    assert edges == expected_edges


def test_3d_grid_mapping(toolkit: SpatialToolkit) -> None:
    """Test that a 3D grid is correctly mapped to a 3D grid graph."""
    # 3D array of shape (2, 2, 2):
    # Layer 0 (z=0):  Layer 1 (z=1):
    # 0  1            4  5
    # 2  3            6  7
    grid = GridMetadata(id="grid_3d", shape=(2, 2, 2))
    graph = toolkit._build_graph(grid)
    data = nx.node_link_data(graph)

    assert isinstance(graph, nx.Graph)
    assert len(data["nodes"]) == 8
    # Edges: a 2x2x2 cube has 12 edges
    assert len(data["edges"]) == 12

    assert [n["id"] for n in data["nodes"]] == list(range(8))

    edges = {tuple(sorted((e["source"], e["target"]))) for e in data["edges"]}

    expected_edges = {
        (0, 1),
        (2, 3),
        (4, 5),
        (6, 7),  # z-edges
        (0, 2),
        (1, 3),
        (4, 6),
        (5, 7),  # y-edges
        (0, 4),
        (1, 5),
        (2, 6),
        (3, 7),  # x-edges
    }
    assert edges == expected_edges


def test_edge_cases_1x1(toolkit: SpatialToolkit) -> None:
    """Test that 1x1 grids work without crashing."""
    grids = [
        GridMetadata(id="1d_single", shape=(1,)),
        GridMetadata(id="2d_single", shape=(1, 1)),
        GridMetadata(id="3d_single", shape=(1, 1, 1)),
    ]

    for grid in grids:
        graph = toolkit._build_graph(grid)
        data = nx.node_link_data(graph)

        assert len(data["nodes"]) == 1
        assert len(data["edges"]) == 0
        assert data["nodes"][0]["id"] == 0


def test_unsupported_dimensions(toolkit: SpatialToolkit) -> None:
    """Test that >3D grids raise a ValueError."""
    grid = GridMetadata(id="4d_grid", shape=(2, 2, 2, 2))

    with pytest.raises(ValueError, match="Unsupported grid dimensions: 4"):
        toolkit._build_graph(grid)
