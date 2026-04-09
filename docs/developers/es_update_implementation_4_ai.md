# ES-MDA Update Plugin Implementation

This document describes the implementation of the Ensemble Smoother (ES-MDA) update algorithm as a GERT plugin. It uses the `iterative_ensemble_smoother` Python package for the mathematical update.

## The Interface

The `ESUpdate` plugin implements the `UpdateAlgorithm` abstract base class:

```python
from abc import ABC, abstractmethod
import polars as pl
from typing import Any
from gert.experiments.models import ParameterMetadata
from gert.updates.spatial import SpatialToolkit

class UpdateAlgorithm(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def perform_update(
        self,
        parameters: pl.DataFrame,
        parameter_metadata: list[ParameterMetadata],
        simulated_responses: pl.DataFrame,
        observations: pl.DataFrame,
        toolkit: SpatialToolkit,
        algorithm_arguments: dict[str, Any],
    ) -> pl.DataFrame:
        pass
```

## Implementation Details & Mathematical Flow

The `perform_update` method orchestrates the update using the library's `ESMDA` or `DistanceESMDA` classes:

### 1. Dependencies
The implementation uses `numpy`, `polars`, and classes from `iterative_ensemble_smoother` (`ESMDA`, `DistanceESMDA`).

### 2. Data Extraction & Reshaping
The library strictly expects features in rows and realizations in columns.

- **Parameters (X)**: Extracted from the `parameters` DataFrame using `parameter_metadata`. For spatial fields (represented as `pl.List`), the data is vertically stacked. The resulting matrix is transposed to shape `(num_parameters, ensemble_size)`.
- **Responses (Y)**: The `simulated_responses` (Tidy/Long format) are joined with `observations` using shared keys. The result is pivoted into a dense matrix and transposed to shape `(num_observations, ensemble_size)`.
- **Observations (d)**: Extracted from the `observations` DataFrame as a 1D array of shape `(num_observations,)`.
- **Covariance (C_D)**: Standard deviations from `observations` are squared to get variances, forming a 1D diagonal array.

### 3. Localization Matrix (Rho)
Localization is handled automatically if `localization_length` is provided in `algorithm_arguments`:

- **Automated Calculation**: The `SpatialToolkit` is used to calculate distance-based localization between parameters and observations.
- **Taper Functions**: Supports `gaspari_cohn` (default), `gaussian`, `step`, and `spherical`.
- **Global Scalars**: Parameters without a `grid_id` (global scalars) are not localized (rho = 1.0).

### 4. Algorithm Arguments & Instantiation
- **Alpha (Inflation)**: The inflation coefficient (default 1.0). If a list is provided, the current iteration index is used.
- **Seed**: `random_seed` for observation perturbations.
- **Outlier Filtering**: Optional `outlier_threshold` to deactivate observations with excessive misfit.

**Instantiate**:
- If `rho` is `None`: Uses `ESMDA`.
- If `rho` is provided: Uses `DistanceESMDA`.

### 5. Execute the Update Lifecycle
The library requires a two-step execution:

1.  **Prepare**: `smoother.prepare_assimilation(Y=Y, truncation=0.99)`
2.  **Assimilate**:
    - For `ESMDA`: `X_updated = smoother.assimilate_batch(X=X)`
    - For `DistanceESMDA`: `X_updated = smoother.assimilate_batch(X_batch=X, Y=Y, rho_batch=rho)`

### 6. Post-Processing & Return
- `X_updated` is transposed back to `(ensemble_size, num_parameters)`.
- Updated values are mapped back to the Polars DataFrame structure (handling both scalar columns and `pl.List` columns).
- The updated DataFrame is joined with non-updatable static columns and returned.

## Plugin Registration
The plugin is registered via entry points in `pyproject.toml`:

```toml
[project.entry-points."gert.update_algorithms"]
es_update = "gert.plugins.es_update:ESUpdate"
```
