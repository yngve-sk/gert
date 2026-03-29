# Context:
I need you to implement the Ensemble Information Filter (EnIF) data assimilation algorithm as a plugin that conforms to a specific `UpdateAlgorithm` Abstract Base Class.

The core mathematical operations for this algorithm are already implemented in an external library called `graphite_maps`. Your task is to write the adapter/wrapper class that properly processes the DataFrames, interacts with the `graphite_maps` API, and returns the updated DataFrame.

## The Interface:
```python
from abc import ABC, abstractmethod
import polars as pl
from typing import Any

class UpdateAlgorithm(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def perform_update(
        self,
        current_parameters: pl.DataFrame,
        simulated_responses: pl.DataFrame,
        observations: pl.DataFrame,
        updatable_parameter_keys: list[str],
        algorithm_arguments: dict[str, Any],
    ) -> pl.DataFrame:
        pass
```

## Implementation Details & Mathematical Flow:
The `perform_update` method needs to orchestrate the update using `graphite_maps` and `scikit-learn` in the following sequence:

### 1. Dependencies:
You will need to use `numpy`, `scipy.sparse`, `sklearn.preprocessing.StandardScaler`, and the following imports from `graphite_maps`:
```python
from graphite_maps.enif import EnIF
from graphite_maps.linear_regression import linear_boost_ic_regression
from graphite_maps.precision_estimation import fit_precision_cholesky_approximate
```

### 2. Data Extraction & Scaling:
*   **Parameters ($X$):** The `current_parameters` arrives as a Wide DataFrame. Spatial 2D/3D grids have been flattened by the Storage API into individual columns (e.g., `porosity_0`, `porosity_1`, `...`, `porosity_99`).
*   The `updatable_parameter_keys` contains the *base names* of the fields (e.g., `["porosity", "fault_mult"]`). You must extract all columns matching exactly, or starting with `{base_name}_`, to build the full matrix.
*   **Important Shape Note:** `graphite_maps` expects the parameter matrix $U$ to be of shape `[n_realizations, n_parameters]`. Ensure the extracted columns are ordered deterministically.
*   **Standardize** the updatable parameters using `sklearn.preprocessing.StandardScaler(copy=True)`. Let's call this `X_scaled`.
*   **Responses ($Y$):** The `simulated_responses` arrives as a massive, vertically stacked Tidy (Long) DataFrame `[realization, <composite_keys...>, value]`.
    *   You must use the composite keys present in the `observations` DataFrame (e.g., `well_id`, `time`) to execute an Inner Join against `simulated_responses`.
    *   This plucks out only the specific simulated values that mathematically align with a physical observation.
    *   Pivot the filtered result into a dense Wide matrix ($Y$) of shape `[n_realizations, n_observations]`, ensuring the columns perfectly align with the row order in `observations`.
*   **Observations ($d$ and $\sigma$):** Extract the observed values ($d$) and their standard deviations ($\sigma$) from the `observations` DataFrame. Both should be 1D arrays of length `n_observations`.

### 3. Learn the Sparse Linear Map ($H$):
Use `graphite_maps` to compute the mapping between the scaled parameters and the simulated responses:
```python
H = linear_boost_ic_regression(U=X_scaled, Y=Y, verbose_level=1)
```

### 4. Build the Prior Precision Matrix ($Prec\_u$):
The total parameter precision matrix is built as a sparse block-diagonal matrix, where each distinct parameter field (e.g., `porosity`, `fault_mult`) constitutes one block on the diagonal.

*   **Graph Dependency:** `fit_precision_cholesky_approximate` computes spatial covariance using a neighborhood graph. Because the Storage API unrolls spatial grids into flat 1D vectors per realization, the graph provides the missing topology.
*   Assume `algorithm_arguments` contains a dictionary mapping parameter base keys to their respective `networkx` graphs (e.g., `algorithm_arguments["parameter_graphs"]["porosity"]`).

For each base name in `updatable_parameter_keys`:
1.  Isolate the specific subset of `X_scaled` corresponding to this parameter's unrolled columns (e.g., all $N$ columns starting with `porosity_`). Let's call this `X_param_scaled` with shape `[N_realizations, N_cells]`.
2.  Retrieve its graph `graph = param_graphs.get(base_name)`.
3.  If no graph is provided, default to `None` (and handle it gracefully by falling back to an independent identity matrix `scipy.sparse.diags([1.0], format="csc")` for scalars).
4.  If a graph is provided, call `fit_precision_cholesky_approximate(X_param_scaled, graph, neighbourhood_expansion=2)` to get the `[N_cells, N_cells]` sub-precision block.
5.  Assemble all these independent sub-matrices into a full sparse block-diagonal matrix `Prec_u` using `scipy.sparse.block_diag(..., format="csc")`.

### 5. Build the Observation Precision Matrix ($Prec\_\epsilon$):
Create a sparse diagonal matrix representing the inverse variance of the observation errors:
```python
Prec_eps = scipy.sparse.diags([1.0 / observation_errors**2], offsets=[0], format="csc")
```

### 6. Execute the EnIF Update:
Instantiate the `EnIF` object and calculate the update:
```python
gtmap = EnIF(Prec_u=Prec_u, Prec_eps=Prec_eps, H=H)

# Determine which parameters are affected by the observations
neighbor_order = algorithm_arguments.get("neighbor_propagation_order", 15)
update_indices = gtmap.get_update_indices(neighbor_propagation_order=neighbor_order)

# Perform the transport update
seed = algorithm_arguments.get("random_seed", None)
X_updated_scaled = gtmap.transport(
    U=X_scaled,
    Y=Y,
    d=observation_values,
    update_indices=update_indices,
    iterative=True,
    seed=seed
)
```

### 7. Post-Processing & Return:
*   Inverse transform `X_updated_scaled` back to the original physical space using the `StandardScaler` fitted in step 2.
*   Create a copy of `current_parameters` and overwrite the unrolled Wide columns belonging to `updatable_parameter_keys` with their newly updated values.
*   Return the completely updated Wide Polars DataFrame.

### 8. Plugin Registration & Project Setup:
In addition to writing the `EnIFUpdate` class, please provide the necessary boilerplate to register this class as a GERT plugin according to the architecture.

*   Create a `registration.py` file that uses the `@gert_plugin` decorator to implement the `gert_update_algorithms` hook, returning an instance of the `EnIFUpdate` class.
*   Provide the snippet for `pyproject.toml` demonstrating how to register the entry point under `[project.entry-points."gert"]`.
*   Name the plugin `"enif_update"` in its `.name` property.

## Task:
Please write the complete Python code for the `EnIFUpdate` class implementing `UpdateAlgorithm`. Ensure thorough docstrings, type hinting, and proper handling of the Polars DataFrames and numpy conversions. Include error handling for missing graphs in `algorithm_arguments`.

---

## Algorithm-Specific Testing: Ensemble Information Filter (EnIF)

Unlike standard ES/Kalman algorithms that compute empirical dense covariance matrices, the EnIF algorithm relies on sparse precision matrix estimation. This requires explicit spatial/neighborhood priors provided via `networkx` parameter graphs.

Because of this unique requirement, the `EnIFUpdate` plugin must have dedicated behavioral tests validating how it consumes the `parameter_graphs` dictionary from `algorithm_arguments`.

### The Graph Topologies to Test

#### 1. The "Isolated Scalars" Case
Scalars (like global fault multipliers, fluid contacts, or single well skins) have no spatial relationship to one another.
*   **Input:** Pass a networkx graph containing $N$ nodes but 0 edges.
*   **Assertion:** The algorithm must complete successfully. Furthermore, an observation that heavily updates Scalar A should have zero (or near-zero) impact on Scalar B, proving that the algorithm respected the conditional independence imposed by the empty graph edges.

#### 2. The "Spatial Field" (Connected Graph) Case
Fields or surfaces are spatially correlated. Updating a grid cell should update its immediate neighbors, but that influence should taper off based on the `neighbor_propagation_order`.
*   **Input:** Pass a networkx graph representing a simple 1D line of 5 connected nodes (e.g., A-B-C-D-E). Set the `neighbor_propagation_order` to 1 in `algorithm_arguments`.
*   **Assertion:** Create an observation that only correlates with node C. After the update:
    *   Node C must update heavily.
    *   Nodes B and D (distance 1) should update moderately.
    *   Nodes A and E (distance 2) should remain completely unchanged (variance and mean identical to prior).

#### 3. The Missing/Malformed Graph Case
The plugin must gracefully handle missing data from the orchestrator.
*   **Input:** Pass `updatable_parameter_keys=["PORO"]` but omit `"PORO"` from the `parameter_graphs` dictionary in `algorithm_arguments`.
*   **Assertion:** The plugin should catch this before passing it to the underlying `graphite_maps` library and raise a clear, actionable ValueError (e.g., "EnIF requires a networkx graph for parameter 'PORO', but none was provided.").
