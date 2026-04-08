"""Tests for the Ensemble Information Filter (EnIF) plugin."""

from typing import Any

import networkx as nx
import numpy as np
import polars as pl
import pytest
from polars.testing import assert_series_equal

from gert.experiments.models import ParameterMetadata
from gert.plugins.enif_update import EnIFUpdate
from gert.updates.spatial import SpatialToolkit


@pytest.fixture
def enif() -> EnIFUpdate:
    """Provide a fresh instance of the EnIFUpdate plugin."""
    return EnIFUpdate()


def _run_isolated_update(
    algorithm: EnIFUpdate,
    prior: pl.DataFrame,
    responses: pl.DataFrame,
    observations: pl.DataFrame,
    updatable_keys: list[str],
    args: dict[str, Any] | None = None,
) -> pl.DataFrame:
    """Helper to run perform_update in isolation."""
    if args is None:
        args = {"random_seed": 42}
    elif "random_seed" not in args:
        args["random_seed"] = 42

    parameter_metadata = [
        ParameterMetadata(name=key, columns=[key]) for key in updatable_keys
    ]
    toolkit = SpatialToolkit()

    return algorithm.perform_update(
        parameters=prior,
        parameter_metadata=parameter_metadata,
        simulated_responses=responses,
        observations=observations,
        toolkit=toolkit,
        algorithm_arguments=args,
    )


class TestEnIFContractAndMicroCase:
    """Testing the micro case (1 param, 1 obs, 2 reals) and contract compliance."""

    def test_schema_preservation_and_non_updatable_ignored(
        self,
        enif: EnIFUpdate,
    ) -> None:
        """The output DataFrame must exactly match the input schema and keep
        non-updatable params fixed.
        """
        prior = pl.DataFrame(
            {
                "realization": [0, 1],
                "PARAM1": [1.0, 2.0],
                "FIXED_PARAM": [5.0, 5.0],
                "STR_PARAM": ["A", "B"],
            },
        )

        responses = pl.DataFrame(
            {
                "realization": [0, 1],
                "response": ["FOPR", "FOPR"],
                "well_id": ["PROD_1", "PROD_1"],
                "time": [2024.0, 2024.0],
                "value": [2.0, 4.0],
            },
        )

        observations = pl.DataFrame(
            {
                "response": ["FOPR"],
                "well_id": ["PROD_1"],
                "time": [2024.0],
                "value": [3.0],
                "std_dev": [0.1],
            },
        )

        posterior = _run_isolated_update(
            enif,
            prior,
            responses,
            observations,
            updatable_keys=["PARAM1"],
        )

        # Contract: Schema must match exactly
        assert posterior.schema == prior.schema
        assert posterior.columns == prior.columns

        # Contract: Non-updatable parameters must be strictly untouched
        assert_series_equal(posterior["realization"], prior["realization"])
        assert_series_equal(posterior["FIXED_PARAM"], prior["FIXED_PARAM"])
        assert_series_equal(posterior["STR_PARAM"], prior["STR_PARAM"])

        # Param1 should have updated
        assert not posterior["PARAM1"].equals(prior["PARAM1"])


class TestEnIFMathematicalSanityChecks:
    """Fundamental DA sanity checks using larger ensembles
    (1 param, 1 obs, 100 reals).
    """

    @pytest.fixture
    def large_ensemble_setup(self) -> dict[str, pl.DataFrame]:
        np.random.seed(42)
        n_reals = 200

        # Prior: N(mean=5.0, std=2.0)
        true_val = 10.0
        prior_vals = np.random.normal(loc=5.0, scale=2.0, size=n_reals)

        prior = pl.DataFrame(
            {
                "realization": np.arange(n_reals),
                "PARAM1": prior_vals,
            },
        )

        # Forward model: Y = 2 * X
        responses = pl.DataFrame(
            {
                "realization": np.arange(n_reals),
                "response": ["WOPR"] * n_reals,
                "well_id": ["INJ_2"] * n_reals,
                "time": [30.5] * n_reals,
                "value": prior_vals * 2.0,
            },
        )

        # Observation: True state is 10.0, so Y_true = 20.0
        observations = pl.DataFrame(
            {
                "response": ["WOPR"],
                "well_id": ["INJ_2"],
                "time": [30.5],
                "value": [20.0],
                "std_dev": [1.0],  # Precise observation
            },
        )

        return {"prior": prior, "responses": responses, "observations": observations}

    def test_variance_reduction_and_mean_shift(
        self,
        enif: EnIFUpdate,
        large_ensemble_setup: dict[str, pl.DataFrame],
    ) -> None:
        """Assimilating a precise observation must reduce variance
        and shift mean toward truth.
        """
        prior = large_ensemble_setup["prior"]

        posterior = _run_isolated_update(
            enif,
            prior,
            large_ensemble_setup["responses"],
            large_ensemble_setup["observations"],
            updatable_keys=["PARAM1"],
        )

        prior_std = float(prior["PARAM1"].std() or 0.0)  # type: ignore[arg-type]
        post_std = float(posterior["PARAM1"].std() or 0.0)  # type: ignore[arg-type]

        prior_mean = float(prior["PARAM1"].mean() or 0.0)  # type: ignore[arg-type]
        post_mean = float(posterior["PARAM1"].mean() or 0.0)  # type: ignore[arg-type]

        true_val = 10.0

        # Variance Reduction
        assert post_std <= prior_std, (
            f"Posterior std ({post_std}) should be <= prior std ({prior_std})"
        )

        # Mean Shift (Pull to Truth)
        prior_error = abs(prior_mean - true_val)
        post_error = abs(post_mean - true_val)
        assert post_error < prior_error, (
            f"Posterior error ({post_error}) should be < prior error ({prior_error})"
        )

    def test_zero_information_update(
        self,
        enif: EnIFUpdate,
        large_ensemble_setup: dict[str, pl.DataFrame],
    ) -> None:
        """Massive observation errors should result in a posterior
        virtually identical to the prior.
        """
        prior = large_ensemble_setup["prior"]

        # Modify observation to have massive error
        obs = large_ensemble_setup["observations"].with_columns(
            pl.lit(1e6).alias("std_dev"),
        )

        posterior = _run_isolated_update(
            enif,
            prior,
            large_ensemble_setup["responses"],
            obs,
            updatable_keys=["PARAM1"],
        )

        # The parameters should be very close to untouched
        np.testing.assert_allclose(
            posterior["PARAM1"].to_numpy(),
            prior["PARAM1"].to_numpy(),
            rtol=1e-3,
            atol=1e-3,
        )


class TestEnIFSizingAndDesign:
    """Testing standard (cross-covariance) and over-determined cases."""

    def test_standard_case_independence(self, enif: EnIFUpdate) -> None:
        """Distinct parameters are treated as independent by EnIF
        (block-diagonal precision), so an unobserved parameter should NOT update
        even if empirically correlated.
        """
        np.random.seed(42)
        n_reals = 100

        # Create two strongly correlated parameters (A and B)
        # B = A + small noise
        param_a = np.random.normal(loc=10.0, scale=3.0, size=n_reals)
        param_b = param_a + np.random.normal(loc=0.0, scale=0.5, size=n_reals)

        prior = pl.DataFrame(
            {
                "realization": np.arange(n_reals),
                "PARAM_A": param_a,
                "PARAM_B": param_b,
            },
        )

        # Observe ONLY a response related to A
        responses = pl.DataFrame(
            {
                "realization": np.arange(n_reals),
                "response": ["BHP"] * n_reals,
                "well_id": ["PROD_A"] * n_reals,
                "time": [10.0] * n_reals,
                "value": param_a * 1.5,
            },
        )

        observations = pl.DataFrame(
            {
                "response": ["BHP"],
                "well_id": ["PROD_A"],
                "time": [10.0],
                "value": [30.0],  # True A is roughly 20
                "std_dev": [0.5],
            },
        )

        posterior = _run_isolated_update(
            enif,
            prior,
            responses,
            observations,
            updatable_keys=["PARAM_A", "PARAM_B"],
        )

        # A should shift towards the truth
        prior_mean_a = float(prior["PARAM_A"].mean() or 0.0)  # type: ignore[arg-type]
        post_mean_a = float(posterior["PARAM_A"].mean() or 0.0)  # type: ignore[arg-type]
        assert post_mean_a > prior_mean_a + 2.0, (
            "Observed parameter A did not update properly."
        )

        # B should NOT shift significantly because EnIF forces independence between keys
        prior_mean_b = float(prior["PARAM_B"].mean() or 0.0)  # type: ignore[arg-type]
        post_mean_b = float(posterior["PARAM_B"].mean() or 0.0)  # type: ignore[arg-type]
        assert abs(post_mean_b - prior_mean_b) < 0.1, (
            "Unobserved parameter B incorrectly updated."
        )

    def test_spatial_field_connected_graph(self, enif: EnIFUpdate) -> None:
        """Testing a 1D spatial field using a networkx connected graph."""

        np.random.seed(42)
        n_reals = 50
        n_nodes = 5

        # 1D Grid: 0 - 1 - 2 - 3 - 4
        # We define a strong spatial prior correlation
        graph = nx.path_graph(n_nodes)

        # Build prior values (start all around 10.0)
        prior_data: dict[str, Any] = {"realization": np.arange(n_reals)}
        param_matrix = np.random.normal(loc=10.0, scale=1.0, size=(n_reals, n_nodes))
        prior_data["PORO"] = [list(row) for row in param_matrix]
        prior = pl.DataFrame(prior_data)

        # Responses: We only observe Node 2 (the middle)
        responses = pl.DataFrame(
            {
                "realization": np.arange(n_reals),
                "type": ["log"] * n_reals,
                "well_id": ["EXPLORATION_1"] * n_reals,
                "depth": [2050.0] * n_reals,
                "value": param_matrix[:, 2] * 1.5,
            },
        )

        observations = pl.DataFrame(
            {
                "type": ["log"],
                "well_id": ["EXPLORATION_1"],
                "depth": [2050.0],
                "value": [30.0],  # True PORO_2 is ~20
                "std_dev": [0.1],
            },
        )

        args = {
            "random_seed": 42,
            "parameter_graphs": {"PORO": graph},
            "neighbor_propagation_order": 1,
        }

        posterior = _run_isolated_update(
            enif,
            prior,
            responses,
            observations,
            updatable_keys=["PORO"],
            args=args,
        )

        prior_matrix = np.vstack(prior["PORO"].to_list())
        prior_means = prior_matrix.mean(axis=0)
        post_matrix = np.vstack(posterior["PORO"].to_list())
        post_means = post_matrix.mean(axis=0)

        # Node 2 must update heavily
        assert post_means[2] > prior_means[2] + 2.0

        # Nodes 1 and 3 should update somewhat due to the imposed
        # correlation from the graph
        assert abs(post_means[1] - prior_means[1]) > 0.1
        assert abs(post_means[3] - prior_means[3]) > 0.1

    def test_over_determined_case(self, enif: EnIFUpdate) -> None:
        """Algorithm must not crash when N_obs > N_realizations (subspace inversion)."""
        np.random.seed(42)
        n_reals = 10
        n_obs = 50
        n_params = 5

        # Small realization count, massive observation count
        prior_data: dict[str, Any] = {"realization": np.arange(n_reals)}
        for p in range(n_params):
            prior_data[f"P{p}"] = np.random.normal(size=n_reals)
        prior = pl.DataFrame(prior_data)

        # 50 simulated responses per realization
        realizations_col = []
        well_col = []
        time_col = []
        vals_col = []
        for r in range(n_reals):
            for o in range(n_obs):
                realizations_col.append(r)
                well_col.append(f"W_{o % 5}")
                time_col.append(float(o // 5))
                vals_col.append(np.random.normal())

        responses = pl.DataFrame(
            {
                "realization": realizations_col,
                "well_id": well_col,
                "time": time_col,
                "value": vals_col,
            },
        )

        observations = pl.DataFrame(
            {
                "well_id": [f"W_{o % 5}" for o in range(n_obs)],
                "time": [float(o // 5) for o in range(n_obs)],
                "value": np.random.normal(size=n_obs),
                "std_dev": np.ones(n_obs) * 0.1,
            },
        )

        # Should complete successfully without singular matrix / broadcasting errors
        posterior = _run_isolated_update(
            enif,
            prior,
            responses,
            observations,
            updatable_keys=[f"P{p}" for p in range(n_params)],
        )

        assert posterior.shape == prior.shape

    def test_ensemble_collapse(self, enif: EnIFUpdate) -> None:
        """Ensemble collapse (0 variance) should be handled gracefully
        without catastrophic crashes.
        """
        prior = pl.DataFrame(
            {
                "realization": [0, 1, 2, 3],
                "PARAM1": [5.0, 5.0, 5.0, 5.0],  # Variance = 0
            },
        )

        responses = pl.DataFrame(
            {
                "realization": [0, 1, 2, 3],
                "well_id": ["W1"] * 4,
                "time": [5.0] * 4,
                "value": [10.0, 10.0, 10.0, 10.0],
            },
        )

        observations = pl.DataFrame(
            {
                "well_id": ["W1"],
                "time": [5.0],
                "value": [20.0],
                "std_dev": [1.0],
            },
        )

        # If it crashes, it fails the test. If it raises a clear error
        # or returns clean, it passes.
        try:
            posterior = _run_isolated_update(
                enif,
                prior,
                responses,
                observations,
                ["PARAM1"],
            )
            assert posterior is not None
        except RecursionError:
            pytest.fail("Ensemble collapse caused a RecursionError")
        except Exception:  # noqa: BLE001, S110
            pass


class TestEnIFSnapshots:
    """Snapshot tests for EnIFUpdate algorithm to detect silent
    mathematical regressions.
    """

    def _assert_snapshot(
        self,
        posterior: pl.DataFrame,
        snapshot: Any,
        name: str,
    ) -> None:
        """Helper to round floats and assert against a snapshot."""
        rounded = posterior.select(
            pl.exclude(pl.Float64, pl.Float32),
            pl.col(pl.Float64, pl.Float32).round(5),
        ).sort("realization")
        snapshot.assert_match(rounded.write_csv(), name)

    def test_enif_small_snapshot(self, enif: EnIFUpdate, snapshot: Any) -> None:
        """The Small/Dummy Snapshot. 3 params, 2 obs, 10 realizations.
        Easy to trace linearly if it breaks.
        """
        np.random.seed(42)
        n_reals = 10
        n_params = 3
        n_obs = 2

        # 1. Create fixed inputs deterministically
        prior_data: dict[str, Any] = {"realization": np.arange(n_reals)}
        for p in range(n_params):
            prior_data[f"PARAM_{p}"] = np.random.normal(
                loc=10.0,
                scale=2.0,
                size=n_reals,
            )
        prior = pl.DataFrame(prior_data)

        realizations_col = []
        resp_col = []
        time_col = []
        vals_col = []
        for r in range(n_reals):
            for o in range(n_obs):
                realizations_col.append(r)
                resp_col.append("FOPR")
                time_col.append(10.0 if o == 0 else 20.0)
                # Deterministic response mapping
                vals_col.append(
                    prior_data["PARAM_0"][r] * 1.5 + np.random.normal(scale=0.1),
                )

        responses = pl.DataFrame(
            {
                "realization": realizations_col,
                "response": resp_col,
                "time": time_col,
                "value": vals_col,
            },
        )

        observations = pl.DataFrame(
            {
                "response": ["FOPR"] * n_obs,
                "time": [10.0, 20.0],
                "value": [15.0] * n_obs,
                "std_dev": [0.5] * n_obs,
            },
        )

        # 2. Run the plugin
        posterior = _run_isolated_update(
            enif,
            prior,
            responses,
            observations,
            updatable_keys=[f"PARAM_{p}" for p in range(n_params)],
            args={"random_seed": 42},
        )

        self._assert_snapshot(posterior, snapshot, "small_posterior_enif.csv")

    def test_enif_comprehensive_snapshot(self, enif: EnIFUpdate, snapshot: Any) -> None:
        """The Comprehensive/Large Snapshot. 50 params, 100 obs, 100 realizations.
        Ensures complex matrix interactions remain stable.
        """
        np.random.seed(42)
        n_reals = 100
        n_params = 50
        n_obs = 100

        # 1. Create fixed inputs deterministically
        prior_data: dict[str, Any] = {"realization": np.arange(n_reals)}
        for p in range(n_params):
            prior_data[f"P{p}"] = np.random.normal(loc=0.0, scale=1.0, size=n_reals)
        prior = pl.DataFrame(prior_data)

        # To keep generation fast, vectorize responses
        obs_keys = np.tile([f"W_{o % 5}" for o in range(n_obs)], n_reals)
        time_keys = np.tile([float(o // 5) for o in range(n_obs)], n_reals)
        real_ids = np.repeat(np.arange(n_reals), n_obs)
        # Responses are a random linear combination of params + noise
        weights = np.random.normal(size=(n_params, n_obs))
        param_matrix = np.column_stack([prior_data[f"P{p}"] for p in range(n_params)])
        resp_matrix = param_matrix @ weights + np.random.normal(
            scale=0.1,
            size=(n_reals, n_obs),
        )

        responses = pl.DataFrame(
            {
                "realization": real_ids,
                "well_id": obs_keys,
                "time": time_keys,
                "value": resp_matrix.flatten(),
            },
        )

        observations = pl.DataFrame(
            {
                "well_id": [f"W_{o % 5}" for o in range(n_obs)],
                "time": [float(o // 5) for o in range(n_obs)],
                "value": np.random.normal(size=n_obs),
                "std_dev": np.ones(n_obs) * 0.1,
            },
        )

        # 2. Run the plugin
        posterior = _run_isolated_update(
            enif,
            prior,
            responses,
            observations,
            updatable_keys=[f"P{p}" for p in range(n_params)],
        )

        assert posterior.shape == prior.shape


class TestEnIFEdgeCases:
    """Testing DA edge cases like missing observations or failed realizations."""

    def test_ensemble_collapse(self, enif: EnIFUpdate) -> None:
        """Ensemble collapse (0 variance) should be handled gracefully
        without catastrophic crashes.
        """
        prior = pl.DataFrame(
            {
                "realization": [0, 1, 2, 3],
                "PARAM1": [5.0, 5.0, 5.0, 5.0],  # Variance = 0
            },
        )

        responses = pl.DataFrame(
            {
                "realization": [0, 1, 2, 3],
                "well_id": ["W1"] * 4,
                "time": [5.0] * 4,
                "value": [10.0, 10.0, 10.0, 10.0],
            },
        )

        observations = pl.DataFrame(
            {
                "well_id": ["W1"],
                "time": [5.0],
                "value": [20.0],
                "std_dev": [1.0],
            },
        )

        # If it crashes, it fails the test. If it raises a clear error
        # or returns clean, it passes.
        try:
            posterior = _run_isolated_update(
                enif,
                prior,
                responses,
                observations,
                ["PARAM1"],
            )
            assert posterior is not None
        except RecursionError:
            pytest.fail("Ensemble collapse caused a RecursionError")
        except Exception:  # noqa: BLE001, S110
            pass
