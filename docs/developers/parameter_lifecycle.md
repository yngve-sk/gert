Parameter Architecture & Lifecycle
This section details how GERT handles parameters from the moment they are loaded from storage, how they are conceptually represented, and how they are injected into Data Assimilation (DA) update algorithms.

1. Core Philosophy: Separation of Math, Meaning, and Space
In ensemble data assimilation, mathematical algorithms require flat, purely numerical matrices. However, geoscientists require logical structures (3D grids, fault blocks, zones). GERT resolves this by decoupling the data into three separate constructs:

The Numbers (State Matrix): The ensemble state is a flat, high-performance Polars DataFrame optimized for linear algebra.

The Space (GridMetadata & Toolkit): The physical coordinates, bounding shapes, and complex fault topologies are defined once globally and managed by the SpatialToolkit.

The Meaning (ParameterMetadata): Lightweight descriptors map the flat numerical columns to the global spatial grids using simple string pointers (grid_id).

2. The Descriptors
Because parameters often share the exact same physical space, GERT uses a "pointer" architecture. We define the grid once, and parameters simply reference it.

The Grid Definition (Global)
This defines the physical arena. It holds the active coordinates and the bounding box for dense reshaping (e.g., handling dead cells).

```python
from typing import Optional, Tuple
import polars as pl
from pydantic import BaseModel

class GridMetadata(BaseModel):
    id: str                    # e.g., "main_reservoir_grid"
    shape: Tuple[int, ...]     # The bounding box (e.g., (Nx, Ny, Nz))

    # Internal server-side storage of coordinates
    # For a 3D grid, this DataFrame has columns ['i', 'j', 'k']
    _coordinates: Optional[pl.DataFrame] = None
```

The Parameter Descriptor (DTO)
This lightweight map connects the flat state matrix to the grid. It contains no dataframes and no math.

```python
from typing import List, Optional
from pydantic import BaseModel, Field

class ParameterMetadata(BaseModel):
    name: str = Field(
        ...,
        description="The logical base name of the parameter (e.g., 'PERM')."
    )
    columns: List[str] = Field(
        ...,
        description="The exact list of corresponding column keys in the state matrix."
    )
    grid_id: Optional[str] = Field(
        default=None,
        description="Pointer to the GridMetadata. None if the parameter is a global scalar."
    )
```

The Strict Alignment Contract
To safely map between the 1D flat numerical state and the 3D spatial grid, GERT enforces a strict row-column contract:

Contract: For any spatial parameter, the exact ordering of keys in ParameterMetadata.columns corresponds 1-to-1 with the row ordering of GridMetadata._coordinates.
E.g., columns[0] strictly represents the spatial cell at _coordinates.row(0).

3. The Lifecycle Phases
Phase 1: Preparation (The Orchestrator)
Before the update algorithm runs:

Grid Registration: The Orchestrator reads the config, identifies the active grids, and registers them with the SpatialToolkit. The toolkit pre-builds the heavy topological graphs (e.g., networkx graphs with faults cut out) only once per grid.

Flattening: It reads the realization data and flattens active parameters into a single Wide Polars DataFrame (parameters).

Descriptor Generation: It generates a ParameterMetadata object for each parameter, assigning the correct columns list and grid_id.

Phase 2: The Interface (The Handoff)
The Orchestrator passes the numbers and metadata into the update algorithm plugin:

```python
def update(
    parameters: pl.DataFrame,          # The pure math (realizations x parameters)
    parameter_metadata: List[ParameterMetadata], # The map: What those columns mean
    observations: List[ObservationMetadata],
    toolkit: SpatialToolkit              # The engine: Holds the pre-built grid graphs
) -> pl.DataFrame:
    ...
```
Phase 3: Inside the Algorithm (Slicing & Lazy Evaluation)
Inside the algorithm, the plugin developer slices the state safely. If they need spatial localization, they use the parameter's grid_id pointer to ask the toolkit for pre-computed metrics.

```python
def localized_enif_update(parameters, parameter_metadata, obs, toolkit):
    updated_state = parameters.clone()

    for param in parameter_metadata:
        # 1. SLICE: Pull out just the numerical columns for this parameter safely
        local_matrix = parameters.select(param.columns).to_numpy()

        # 2. LOCALIZE (Lazy Evaluation via Pointers)
        distances = None
        if param.grid_id is not None:
            # The toolkit uses the grid_id pointer to instantly fetch
            # the already-built topological graph and compute distances.
            distances = toolkit.calculate_localization(
                grid_id=param.grid_id,
                obs_meta=obs
            )

        # 3. UPDATE: Run DA math (EnIF, ES-MDA, etc.)
        updated_local_matrix = run_da_math(local_matrix, obs, distances)

        # 4. REINSERT: Update the Polars dataframe
        updated_df = pl.DataFrame(updated_local_matrix, schema=param.columns)
        updated_state = updated_state.update(updated_df)

    return updated_state
```

4. Deep Dive: Space, Topologies, and Faults
A common trap in DA architectures is copying spatial structures for every variable. In GERT, both Porosity and Permeability share the exact same grid_id.

The Lightweight Topology Model (Why we don't pass the EGRID)
Traditional reservoir modeling passes the entire heavy EGRID (containing X, Y, Z coordinates for all 8 cell corners) into the update step, forcing algorithms to do heavy geometry math to find neighbors.

GERT completely bypasses this by using logical [i, j, k] coordinates as the universal shared language. A standard [i, j, k] grid is implicitly a perfect 3D lattice. The SpatialToolkit only needs to be fed the exceptions to that lattice (Faults and Inactive Cells) defined in the configuration.

How Faults Intersect with the Grid:

The Orchestrator initializes the SpatialToolkit with a list of broken fault connections.

The toolkit builds the 3D lattice for main_reservoir_grid based on the GridMetadata.shape.

It cross-references the master fault list and deletes the edges where faults exist.

When the algorithm requests distances for any parameter pointing to main_reservoir_grid, the toolkit calculates the shortest path on this pre-broken graph.

Because the heavy topology is cached behind a grid_id pointer, we get all the localization accuracy of the EGRID with zero graph-rebuilding overhead during the update loops.
