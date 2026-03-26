Context:I need you to implement the Ensemble Information Filter (EnIF) data assimilation algorithm as a plugin that conforms to a specific UpdateAlgorithm Abstract Base Class.The core mathematical operations for this algorithm are already implemented in an external library called graphite_maps. Your task is to write the adapter/wrapper class that properly processes the DataFrames, interacts with the graphite_maps API, and returns the updated DataFrame.The Interface:Pythonfrom abc import ABC, abstractmethod
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
Implementation Details & Mathematical Flow:The perform_update method needs to orchestrate the update using graphite_maps and scikit-learn in the following sequence:1. Dependencies:You will need to use numpy, scipy.sparse, sklearn.preprocessing.StandardScaler, and the following imports from graphite_maps:Pythonfrom graphite_maps.enif import EnIF
from graphite_maps.linear_regression import linear_boost_ic_regression
from graphite_maps.precision_estimation import fit_precision_cholesky_approximate
2. Data Extraction & Scaling:Parameters ($X$): Extract only the columns specified in updatable_parameter_keys from current_parameters. Convert this to a numpy array.Important Shape Note: graphite_maps expects the parameter matrix $U$ to be of shape [n_realizations, n_parameters].Standardize the updatable parameters using sklearn.preprocessing.StandardScaler(copy=True). Let's call this X_scaled.Responses ($Y$): Extract the values from simulated_responses into a numpy array of shape [n_realizations, n_observations].Observations ($d$ and $\sigma$): Extract the observed values ($d$) and their standard deviations ($\sigma$) from the observations DataFrame. Both should be 1D arrays of length n_observations.3. Learn the Sparse Linear Map ($H$):Use graphite_maps to compute the mapping between the scaled parameters and the simulated responses:PythonH = linear_boost_ic_regression(U=X_scaled, Y=Y, verbose_level=1)
4. Build the Prior Precision Matrix ($Prec\_u$):The parameter precision matrix is built as a sparse block-diagonal matrix.Graph Dependency: fit_precision_cholesky_approximate requires a neighborhood graph for the parameters. Because our API receives flat parameters, assume that algorithm_arguments contains a dictionary mapping parameter keys to their respective networkx graphs (e.g., algorithm_arguments["parameter_graphs"]). If no graph is provided for a parameter, default to None (or handle it gracefully).For each parameter in updatable_parameter_keys:Extract its specific scaled column(s).Call fit_precision_cholesky_approximate(X_param_scaled, graph, neighbourhood_expansion=2) to get the sub-precision matrix.Assemble these sub-matrices into a full sparse block-diagonal matrix Prec_u using scipy.sparse.block_diag(..., format="csc").5. Build the Observation Precision Matrix ($Prec\_\epsilon$):Create a sparse diagonal matrix representing the inverse variance of the observation errors:PythonPrec_eps = scipy.sparse.diags([1.0 / observation_errors**2], offsets=[0], format="csc")
6. Execute the EnIF Update:Instantiate the EnIF object and calculate the update:Pythongtmap = EnIF(Prec_u=Prec_u, Prec_eps=Prec_eps, H=H)

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
7. Post-Processing & Return:Inverse transform X_updated_scaled back to the original physical space using the StandardScaler fitted in step 2.Create a copy of current_parameters and overwrite the columns in updatable_parameter_keys with their newly updated values.Return the updated Polars DataFrame.
8.Plugin Registration & Project Setup:
In addition to writing the EnIFUpdate class, please provide the necessary boilerplate to register this class as a GERT plugin according to the architecture.

Create a registration.py file that uses the @gert_plugin decorator to implement the gert_update_algorithms hook, returning an instance of the EnIFUpdate class.

Provide the snippet for pyproject.toml demonstrating how to register the entry point under [project.entry-points."gert"].

Name the plugin "enif_update" in its .name property.

Task:Please write the complete Python code for the EnIFUpdate class implementing UpdateAlgorithm. Ensure thorough docstrings, type hinting, and proper handling of the Polars DataFrames and numpy conversions. Include error handling for missing graphs in algorithm_arguments.
