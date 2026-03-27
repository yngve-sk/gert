Context:
I need you to implement an Ensemble Smoother (ES) update algorithm as a plugin that conforms to a specific UpdateAlgorithm Abstract Base Class.

You must use the iterative_ensemble_smoother Python package for the mathematical update. Your task is to write the ESUpdateStep class that processes the Polars DataFrames, handles error inflation and localization, interacts with the library's Object-Oriented API (ESMDA or LocalizedESMDA), and returns the updated DataFrame.

The Interface:

Python
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
Implementation Details & Mathematical Flow:

The perform_update method needs to orchestrate the update using the library's API (ESMDA or LocalizedESMDA):

1. Dependencies:
You will need to use numpy and imports from iterative_ensemble_smoother (ESMDA, LocalizedESMDA).

2. Data Extraction & Reshaping:
The library strictly expects features in rows and realizations in columns.

Parameters (X): `current_parameters` arrives as a Wide DataFrame where spatial 2D/3D grids have been flattened by the Storage API into individual columns (e.g., `porosity_0`, `porosity_1`). `updatable_parameter_keys` contains the *base names* (e.g., `["porosity"]`). Extract all unrolled columns matching or starting with `{base_name}_`. Transpose the resulting matrix to a numpy array of shape `(num_parameters, ensemble_size)`.

Responses (Y): The `simulated_responses` arrives as a massive, vertically stacked Tidy (Long) DataFrame `[realization, <composite_keys...>, value]`.
Use the composite keys present in the `observations` DataFrame (e.g., `well_id`, `time`) to execute an Inner Join against `simulated_responses`. Pivot the filtered result into a dense matrix of shape `(ensemble_size, num_observations)`, ensuring columns perfectly align with the rows of `observations`. Finally, transpose it to a numpy array of shape `(num_observations, ensemble_size)` as required by the library.

Observations (d): Extract the observed values from the `observations` DataFrame as a 1D numpy float array of shape `(num_observations,)`.

Covariance (C
D
​
 ): Extract the standard deviations from the observations DataFrame. Square them to get variances, and create a 1D numpy float array of shape (num_observations,). The library accepts 1D arrays for diagonal covariance matrices.

3. Algorithm Arguments & Instantiation:

Alpha (Inflation): Extract the alpha coefficient from algorithm_arguments (default 1.0).

Important Note on the Library: The ESMDA class normalizes the alpha array on __init__. Because this plugin performs a single step update, passing a single [alpha] might get normalized to 1.0 by the library. To force the library to use the exact alpha for this single step without normalization mutating it, you may need to temporarily mock/patch the normalize_alpha behavior or pass a dummy array like np.array([alpha, alpha / (alpha - 1)]) and only execute the first iteration. Handle this normalization trap carefully so the exact alpha inflation factor is applied.

Seed: Extract random_seed from algorithm_arguments (default None).

Localization (Rho): Extract rho from algorithm_arguments (default None).

Instantiate: If rho is None:

Python
smoother = ESMDA(covariance=C_D, observations=d, alpha=alpha_array, seed=seed)
If rho is provided:

Python
smoother = LocalizedESMDA(covariance=C_D, observations=d, alpha=alpha_array, seed=seed)
4. Execute the Update Lifecycle:
The library requires a strict two-step execution:

Prepare: ```python
smoother.prepare_assimilation(Y=Y, truncation=0.99)

Assimilate:
If using ESMDA:

Python
X_updated = smoother.assimilate_batch(X=X)
If using LocalizedESMDA, you must define a callback that applies the Hadamard (element-wise) product of the Kalman gain K and the localization matrix rho. Note: K has shape (num_parameters, num_observations), so ensure rho aligns with this.

Python
def loc_func(K: np.ndarray) -> np.ndarray:
    return K * rho
X_updated = smoother.assimilate_batch(X=X, localization_callback=loc_func)
5. Post-Processing & Return:

Transpose `X_updated` back to the shape `(ensemble_size, num_parameters)`.

Create a copy of `current_parameters` and overwrite the unrolled Wide columns belonging to `updatable_parameter_keys` with the newly calculated values.

Return the updated Wide Polars DataFrame.

6. Plugin Registration & Project Setup:
Please provide the necessary boilerplate to register this class as a GERT plugin:

Create a registration.py file that uses the @gert_plugin decorator to implement the gert_update_algorithms hook, returning an instance of the ESUpdateStep class.

Provide the snippet for pyproject.toml demonstrating how to register the entry point under [project.entry-points."gert"].

Name the plugin "es_update" in its .name property.

Task:
Please write the complete Python code for the ESUpdateStep plugin and the registration.py file. Ensure thorough docstrings, type hinting, proper handling of the Polars DataFrames, and exact matrix transpositions expected by iterative_ensemble_smoother. Include the branching logic to use LocalizedESMDA when rho is provided.
