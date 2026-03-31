"""Ensemble Information Filter (EnIF) plugin."""

from typing import Any

import networkx as nx
import numpy as np
import polars as pl
import scipy.sparse as sp
from graphite_maps.enif import EnIF
from graphite_maps.linear_regression import linear_boost_ic_regression
from graphite_maps.precision_estimation import fit_precision_cholesky_approximate
from sklearn.preprocessing import StandardScaler

from gert.updates.base import UpdateAlgorithm


class EnIFUpdate(UpdateAlgorithm):
    """Ensemble Information Filter update algorithm.

    This plugin acts as an adapter to the graphite_maps library for
    performing iterative ensemble-based data assimilation updates.
    """

    @property
    def name(self) -> str:
        return "enif_update"

    def perform_update(
        self,
        current_parameters: pl.DataFrame,
        simulated_responses: pl.DataFrame,
        observations: pl.DataFrame,
        updatable_parameter_keys: list[str],
        algorithm_arguments: dict[str, Any],
    ) -> pl.DataFrame:
        # 1. Sort DataFrames to ensure deterministic realization order
        current_parameters = current_parameters.sort("realization")

        # 1.a Identify Parameter Categories
        all_cols = current_parameters.columns
        static_cols = [
            c
            for c in all_cols
            if c not in updatable_parameter_keys and c != "realization"
        ]

        # 2. Isolate Static Data
        static_params_df = current_parameters.select(["realization", *static_cols])

        # 3. Extract Updatable Parameters (X)
        x_arrays = []
        block_indices = []
        current_col_idx = 0

        for key in updatable_parameter_keys:
            series = current_parameters[key]

            # Convert to 2D numpy array [n_realizations, n_features]
            if "List" in str(series.dtype) or "Array" in str(series.dtype):
                # pl.Series of lists -> 2D numpy array
                arr = np.vstack(series.to_list())
            else:
                # scalar column -> [n_realizations, 1]
                arr = series.to_numpy().reshape(-1, 1)

            n_features = arr.shape[1]
            block_indices.append((key, current_col_idx, current_col_idx + n_features))
            x_arrays.append(arr)
            current_col_idx += n_features

        if not x_arrays:
            return current_parameters.clone()

        X = np.hstack(x_arrays)
        scaler = StandardScaler(copy=True)
        X_scaled = scaler.fit_transform(X)

        # 4. Extract Observations (d and sigma)
        d = observations["value"].to_numpy()
        sigma = observations["std_dev"].to_numpy()
        n_observations = len(d)

        # 5. Extract Responses (Y)
        # Execute an Inner Join against the massive Tidy simulated_responses universe.
        obs_df = observations.with_row_index("obs_idx")
        key_cols = [
            c for c in obs_df.columns if c not in {"obs_idx", "value", "std_dev"}
        ]

        df_resp = simulated_responses.rename({"value": "sim_value"})
        shared_keys = [c for c in key_cols if c in df_resp.columns]

        if not shared_keys:
            msg = (
                "No shared composite keys to join observations and simulated responses."
            )
            raise ValueError(msg)

        joined = df_resp.join(obs_df, on=shared_keys, how="inner")
        if joined.is_empty():
            obs_sample = observations.select(key_cols).unique().head(10).to_dicts()
            resp_sample = df_resp.select(shared_keys).unique().head(10).to_dicts()
            msg = (
                "No simulated responses matched the provided observations.\n"
                f"Joined on keys: {shared_keys}\n"
                f"Observation keys (sample): {obs_sample}\n"
                f"Response keys (sample): {resp_sample}"
            )
            raise ValueError(msg)

        # Pivot into the Dense Wide Matrix [N_reals, N_obs]
        wide_resp = joined.pivot(
            values="sim_value",
            index="realization",
            on="obs_idx",
        )

        # Check for any missing observations
        missing_obs = [
            str(i) for i in range(len(obs_df)) if str(i) not in wide_resp.columns
        ]
        if missing_obs:
            first_missing = obs_df.filter(pl.col("obs_idx") == int(missing_obs[0]))
            obs_identity = ", ".join(
                f"{k}={first_missing[k][0]}"
                for k in key_cols
                if k in first_missing.columns and first_missing[k][0] is not None
            )
            msg = (
                f"Missing simulated responses for observation ({obs_identity}). "
                f"Total missing indices: {missing_obs}"
            )
            raise ValueError(msg)

        # Align the columns perfectly with the `d` vector ordering
        ordered_cols = [str(i) for i in range(n_observations)]
        Y = wide_resp.select(ordered_cols).to_numpy()

        # 6. Learn the Sparse Linear Map (H)
        H = linear_boost_ic_regression(U=X_scaled, Y=Y, verbose_level=1)

        # 7. Build the Prior Precision Matrix (Prec_u)
        prec_matrices = []
        param_graphs = algorithm_arguments.get("parameter_graphs", {})

        for base_key, start_idx, end_idx in block_indices:
            X_param_scaled = X_scaled[:, start_idx:end_idx]
            graph = param_graphs.get(base_key)

            if graph is None and X_param_scaled.shape[1] == 1:
                # Fallback for independent scalar parameters
                sub_prec = sp.diags([1.0], offsets=[0], format="csc")
            elif graph is None:
                # Check for grid_dimensions in algorithm_arguments
                grid_dims = algorithm_arguments.get("grid_dimensions")
                if grid_dims and isinstance(grid_dims, list) and len(grid_dims) == 2:
                    nx_dim, ny_dim = grid_dims[0], grid_dims[1]
                    if nx_dim * ny_dim != X_param_scaled.shape[1]:
                        msg = (
                            f"grid_dimensions {grid_dims} do not match the number of "
                            f"features ({X_param_scaled.shape[1]}) for parameter '{base_key}'."
                        )
                        raise ValueError(msg)

                    # Create a 2D grid graph and map tuple nodes to integers
                    grid_graph = nx.grid_2d_graph(nx_dim, ny_dim)
                    mapping = {(i, j): i * ny_dim + j for (i, j) in grid_graph.nodes()}
                    graph = nx.relabel_nodes(grid_graph, mapping)
                else:
                    msg = f"EnIF requires a networkx graph for spatial parameter '{base_key}', but none was provided."
                    raise ValueError(msg)

            if graph is not None:
                sub_prec = fit_precision_cholesky_approximate(
                    X_param_scaled,
                    graph,
                    neighbourhood_expansion=2,
                )
            prec_matrices.append(sub_prec)

        Prec_u = sp.block_diag(prec_matrices, format="csc")

        # 8. Build Observation Precision Matrix (Prec_eps)
        Prec_eps = sp.diags([1.0 / sigma**2], offsets=[0], format="csc")

        # 9. Execute the EnIF Update
        gtmap = EnIF(Prec_u=Prec_u, Prec_eps=Prec_eps, H=H)

        neighbor_order = algorithm_arguments.get("neighbor_propagation_order", 15)
        update_indices = gtmap.get_update_indices(
            neighbor_propagation_order=neighbor_order,
        )

        seed = algorithm_arguments.get("random_seed")
        X_updated_scaled = gtmap.transport(
            U=X_scaled,
            Y=Y,
            d=d,
            update_indices=update_indices,
            iterative=True,
            seed=seed,
        )

        # 10. Post-Processing & Construct Final DataFrame
        X_updated = scaler.inverse_transform(X_updated_scaled)

        # Construct updated_params_df
        updated_columns = [current_parameters["realization"]]

        for key, start_idx, end_idx in block_indices:
            updated_data = X_updated[:, start_idx:end_idx]

            if end_idx - start_idx == 1 and "List" not in str(
                current_parameters[key].dtype,
            ):
                # Write back as scalar
                updated_columns.append(pl.Series(name=key, values=updated_data[:, 0]))
            else:
                # Write back as List
                updated_columns.append(
                    pl.Series(name=key, values=updated_data.tolist()),
                )

        updated_params_df = pl.DataFrame(updated_columns)

        # Join with static parameters
        return updated_params_df.join(static_params_df, on="realization", how="left")
