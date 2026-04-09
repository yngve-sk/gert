"""Ensemble Smoother (ES-MDA) update plugin."""

import logging
from typing import Any

import numpy as np
import polars as pl
from iterative_ensemble_smoother import (
    ESMDA,
)
from iterative_ensemble_smoother.experimental import (
    DistanceESMDA,
)

from gert.experiments.models import ParameterMetadata
from gert.updates.base import UpdateAlgorithm
from gert.updates.spatial import SpatialToolkit

logger = logging.getLogger(__name__)


class ESUpdate(UpdateAlgorithm):
    # ruff: noqa: N806, E501, C901
    # ruff: noqa: N806, E501, C901
    """Ensemble Smoother (ES-MDA) update algorithm.

    This plugin performs a single mathematical assimilation step using the
    iterative_ensemble_smoother library. It supports both global ESMDA and
    localized updates (LocalizedESMDA).

    Expected `algorithm_arguments`:
        - `alpha` (float): The inflation coefficient for this step. Default is 1.0.
        - `random_seed` (int): Optional seed for observation perturbations.
    """

    @property
    def name(self) -> str:
        return "es_update"

    def perform_update(
        self,
        parameters: pl.DataFrame,
        parameter_metadata: list[ParameterMetadata],
        simulated_responses: pl.DataFrame,
        observations: pl.DataFrame,
        toolkit: SpatialToolkit,
        algorithm_arguments: dict[str, Any],
    ) -> pl.DataFrame:
        # 1. Sort DataFrames to ensure deterministic realization order
        parameters = parameters.sort("realization")

        # 2. Extract Updatable Parameters (X)
        # The library expects shape (num_parameters, ensemble_size)
        x_arrays = []
        block_indices = []
        current_feat_idx = 0

        updatable_cols = []
        for pm in parameter_metadata:
            updatable_cols.extend(pm.columns)
            sub_df = parameters.select(pm.columns)

            if len(pm.columns) == 1:
                series = sub_df.to_series()
                if "List" in str(series.dtype) or "Array" in str(series.dtype):
                    arr = np.vstack(series.to_list())
                else:
                    arr = series.to_numpy().reshape(-1, 1)
            else:
                arr = sub_df.to_numpy()

            n_features = arr.shape[1]
            block_indices.append((pm, current_feat_idx, current_feat_idx + n_features))
            x_arrays.append(arr)
            current_feat_idx += n_features

        if not x_arrays:
            return parameters.clone()

        # X shape: (ensemble_size, num_parameters) -> Transpose to (num_parameters, ensemble_size)
        X = np.hstack(x_arrays).T

        # 2.5 Build Localization Matrix (Rho) if requested
        localization_length = algorithm_arguments.get("localization_length")
        rho = None

        if localization_length is not None:
            # ERT supports lists for anisotropy, or a single float
            if isinstance(localization_length, float) and localization_length <= 0:
                pass
            else:
                rho_blocks = []
                taper_func = algorithm_arguments.get("taper_function", "gaspari_cohn")
                for pm, start_idx, end_idx in block_indices:
                    n_feats = end_idx - start_idx
                    if pm.grid_id is None:
                        # Global scalars are not localized (correlation = 1.0)
                        rho_blocks.append(np.ones((n_feats, len(observations))))
                    else:
                        loc_matrix = toolkit.calculate_localization(
                            grid_id=pm.grid_id,
                            obs_meta=observations,
                            base_length=localization_length,
                            taper_function=taper_func,
                        )
                        if loc_matrix is None:
                            rho_blocks.append(np.ones((n_feats, len(observations))))
                        else:
                            rho_blocks.append(loc_matrix)

                if rho_blocks:
                    rho = np.vstack(rho_blocks)

        # 3. Extract Observations (d) and Covariance (C_D)
        # d shape: (num_observations,)
        # C_D shape: (num_observations,) for diagonal
        d = observations["value"].to_numpy()
        sigma = observations["std_dev"].to_numpy()
        C_D = sigma**2
        n_observations = len(d)

        # 4. Extract Responses (Y)
        # Pivot into Dense Wide Matrix [N_reals, N_obs]
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
            msg = "No simulated responses matched the provided observations."
            raise ValueError(msg)

        wide_resp = joined.pivot(
            values="sim_value",
            index="realization",
            on="obs_idx",
        ).sort("realization")

        # Align columns perfectly with `d` vector ordering [0, 1, ..., n_obs-1]
        ordered_cols = [str(i) for i in range(n_observations)]
        # Y shape: (ensemble_size, num_observations) -> Transpose to (num_observations, ensemble_size)
        Y = wide_resp.select(ordered_cols).to_numpy().T

        # 4.5 Observation Filtering (Outliers & Ensemble Collapse)
        Y_stds = np.std(Y, axis=1)
        Y_means = np.mean(Y, axis=1)

        active_mask = np.ones(n_observations, dtype=bool)

        # Deactivate responses where the ensemble has collapsed (0 variance)
        collapse_mask = Y_stds <= 1e-8
        if np.any(collapse_mask):
            active_mask &= ~collapse_mask

        # Deactivate outliers
        outlier_threshold = algorithm_arguments.get("outlier_threshold")
        if outlier_threshold is not None:
            misfit = np.abs(Y_means - d) / sigma
            outlier_mask = misfit > outlier_threshold
            if np.any(outlier_mask):
                active_mask &= ~outlier_mask

        if not np.all(active_mask):
            dropped_indices = np.where(~active_mask)[0]
            dropped_obs = observations[dropped_indices]

            # Create a string representation of dropped keys for logging
            dropped_key_cols = [
                c for c in dropped_obs.columns if c not in {"value", "std_dev"}
            ]
            dropped_repr = dropped_obs.select(dropped_key_cols).to_dicts()

            logger.warning(
                f"Deactivating {len(dropped_indices)} observations due to outliers or zero variance: {dropped_repr}",
            )

            if not np.any(active_mask):
                logger.warning("All observations deactivated. Returning prior.")
                return parameters.clone()

            Y = Y[active_mask, :]
            d = d[active_mask]
            sigma = sigma[active_mask]
            C_D = sigma**2
            n_observations = len(d)

            if rho is not None:
                rho = rho[:, active_mask]

        # 5. Algorithm Arguments & Instantiation
        weights_arg = algorithm_arguments.get("weights")
        if weights_arg is not None:
            weights = np.array(weights_arg, dtype=float)
            # Clip near-zero weights to prevent division by zero in ies.ESMDA alpha inversion
            weights = np.clip(weights, 1e-12, None)
            weights /= np.sum(weights)
            # The user explicitly asked for the normalized weights to be passed as alpha
            # ies.ESMDA will internally re-normalize this using its own `normalize_alpha`
            # or treat it as the inflation array.
            alpha = weights
        else:
            alpha_arg = algorithm_arguments.get("alpha", 1)
            if isinstance(alpha_arg, list):
                alpha = np.array(alpha_arg, dtype=float)
            elif isinstance(alpha_arg, float) and alpha_arg.is_integer():
                alpha = int(alpha_arg)
            else:
                alpha = alpha_arg

        seed = algorithm_arguments.get("random_seed")

        if rho is None:
            smoother = ESMDA(
                covariance=C_D,
                observations=d,
                alpha=alpha,
                seed=seed,
            )
        else:
            # rho must have shape (num_parameters, num_observations)
            if rho.shape != (X.shape[0], n_observations):
                msg = f"Localization matrix rho has wrong shape {rho.shape}, expected {(X.shape[0], n_observations)}"
                raise ValueError(msg)

            smoother = DistanceESMDA(
                covariance=C_D,
                observations=d,
                alpha=alpha,
                seed=seed,
            )

        # Allow selecting the specific iteration index if provided (for when alpha is a list)
        current_iteration = algorithm_arguments.get("current_iteration", 0)
        smoother.iteration = current_iteration - 1

        if rho is not None:
            # WORKAROUND: DistanceESMDA inherits from ESMDA (which normalizes alpha into an array),
            # but its `prepare_assimilation` method incorrectly treats `self.alpha` as a scalar,
            # causing broadcast errors during `self.alpha * (N_e - 1)`.
            # We explicitly patch `self.alpha` to be the scalar value for the current iteration.
            smoother.alpha = smoother.alpha[current_iteration]

        # 6. Execute Update Lifecycle
        if rho is None:
            # Prepare: Computes the Kalman gain (or intermediate matrices)
            smoother.prepare_assimilation(Y=Y, truncation=0.99)
            X_updated = smoother.assimilate_batch(X=X)
        else:
            # DistanceESMDA requires Y and rho_batch to be passed directly to assimilate_batch,
            # and automatically calls prepare_assimilation internally if self.X3 is None.
            # But we can also call it explicitly to be safe.
            smoother.prepare_assimilation(Y=Y, truncation=0.99)
            X_updated = smoother.assimilate_batch(
                X_batch=X,
                Y=Y,
                rho_batch=rho,
                truncation=0.99,
            )

        # X_updated shape is (num_parameters, ensemble_size) -> Transpose back
        X_updated = X_updated.T

        # 7. Post-Processing & Construct Final DataFrame
        all_cols = parameters.columns
        static_cols = [
            c for c in all_cols if c not in updatable_cols and c != "realization"
        ]
        static_params_df = parameters.select(["realization", *static_cols])

        updated_columns = [parameters["realization"]]

        for pm, start_idx, end_idx in block_indices:
            updated_data = X_updated[:, start_idx:end_idx]

            if len(pm.columns) == 1:
                series = parameters[pm.columns[0]]
                if "List" not in str(series.dtype) and "Array" not in str(series.dtype):
                    updated_columns.append(
                        pl.Series(
                            name=pm.columns[0],
                            values=updated_data[:, 0],
                            dtype=pl.Float64,
                        ),
                    )
                else:
                    updated_columns.append(
                        pl.Series(
                            name=pm.columns[0],
                            values=updated_data.tolist(),
                            dtype=pl.List(pl.Float64),
                        ),
                    )
            else:
                for i, col_name in enumerate(pm.columns):
                    updated_columns.append(
                        pl.Series(
                            name=col_name,
                            values=updated_data[:, i],
                            dtype=pl.Float64,
                        ),
                    )

        updated_params_df = pl.DataFrame(updated_columns)

        # Join with static parameters
        return updated_params_df.join(static_params_df, on="realization", how="left")
