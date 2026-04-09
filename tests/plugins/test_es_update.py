"""Tests for the Ensemble Smoother (ES-MDA) plugin."""

from typing import Any

import numpy as np
import polars as pl
import pytest
from polars.testing import assert_series_equal

from gert.experiments.models import ParameterMetadata
from gert.plugins.es_update import ESUpdate
from gert.updates.spatial import SpatialToolkit


@pytest.fixture
def es() -> ESUpdate:
    """Provide a fresh instance of the ESUpdate plugin."""
    return ESUpdate()


def _run_isolated_update(
    algorithm: ESUpdate,
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


class TestESContractAndMicroCase:
    """Testing the micro case (1 param, 1 obs, 2 reals) and contract compliance."""

    def test_schema_preservation_and_non_updatable_ignored(
        self,
        es: ESUpdate,
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
            es,
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


class TestESMathematicalSanityChecks:
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
        es: ESUpdate,
        large_ensemble_setup: dict[str, pl.DataFrame],
    ) -> None:
        """Assimilating a precise observation must reduce variance
        and shift mean toward truth.
        """
        prior = large_ensemble_setup["prior"]

        posterior = _run_isolated_update(
            es,
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
        es: ESUpdate,
        large_ensemble_setup: dict[str, pl.DataFrame],
    ) -> None:
        """Massive observation errors should result in a posterior
        virtually identical to the prior.
        """
        prior = large_ensemble_setup["prior"]

        # Modify observation to have massive error
        obs = large_ensemble_setup["observations"].with_columns(
            pl.lit(1e12).alias("std_dev"),
        )

        posterior = _run_isolated_update(
            es,
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


class TestESSizingAndDesign:
    """Testing standard (cross-covariance) and over-determined cases."""

    def test_standard_case_correlation(self, es: ESUpdate) -> None:
        """Standard ES DOES update correlated unobserved parameters."""
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
            es,
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

        # B should ALSO shift significantly because ES respects empirical correlation
        prior_mean_b = float(prior["PARAM_B"].mean() or 0.0)  # type: ignore[arg-type]
        post_mean_b = float(posterior["PARAM_B"].mean() or 0.0)  # type: ignore[arg-type]
        assert post_mean_b > prior_mean_b + 2.0, (
            "Unobserved parameter B did not update via correlation."
        )

    def test_alpha_inflation(self, es: ESUpdate) -> None:
        """Higher alpha should lead to a smaller update (larger perceived noise)."""
        np.random.seed(42)
        n_reals = 100

        prior_vals = np.random.normal(loc=5.0, scale=1.0, size=n_reals)
        prior = pl.DataFrame({"realization": np.arange(n_reals), "P1": prior_vals})

        responses = pl.DataFrame(
            {
                "realization": np.arange(n_reals),
                "response": ["R1"] * n_reals,
                "time": [1.0] * n_reals,
                "value": prior_vals,
            },
        )

        observations = pl.DataFrame(
            {
                "response": ["R1"],
                "time": [1.0],
                "value": [10.0],
                "std_dev": [0.1],
            },
        )

        # Update with alpha=1.0
        post_1 = _run_isolated_update(
            es,
            prior,
            responses,
            observations,
            ["P1"],
            {"alpha": 1.0},
        )
        # Update with alpha=10.0
        post_10 = _run_isolated_update(
            es,
            prior,
            responses,
            observations,
            ["P1"],
            {"alpha": 10.0},
        )

        shift_1 = abs(float(str(post_1["P1"].mean())) - float(str(prior["P1"].mean())))
        shift_10 = abs(
            float(str(post_10["P1"].mean())) - float(str(prior["P1"].mean())),
        )

        assert shift_10 < shift_1, "Alpha inflation did not reduce the update shift."

    def test_over_determined_case(self, es: ESUpdate) -> None:
        """Algorithm must not crash when N_obs > N_realizations (subspace inversion)."""
        np.random.seed(42)
        n_reals = 10
        n_obs = 50
        n_params = 5

        prior_data: dict[str, Any] = {"realization": np.arange(n_reals)}
        for p in range(n_params):
            prior_data[f"P{p}"] = np.random.normal(size=n_reals)
        prior = pl.DataFrame(prior_data)

        realizations_col = []
        well_col = []
        time_col = []
        vals_col = []
        for r in range(n_reals):
            for o in range(n_obs):
                realizations_col.append(r)
                well_col.append(f"W_{o}")
                time_col.append(0.0)
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
                "well_id": [f"W_{o}" for o in range(n_obs)],
                "time": [0.0] * n_obs,
                "value": np.random.normal(size=n_obs),
                "std_dev": np.ones(n_obs) * 0.1,
            },
        )

        posterior = _run_isolated_update(
            es,
            prior,
            responses,
            observations,
            [f"P{p}" for p in range(n_params)],
        )

        assert posterior.shape == prior.shape


class TestESSnapshots:
    """Snapshot tests for ESUpdate algorithm to detect silent
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

    def test_es_small_snapshot(self, es: ESUpdate, snapshot: Any) -> None:
        """The Small/Dummy Snapshot."""
        np.random.seed(42)
        n_reals = 10
        n_params = 3
        n_obs = 2

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

        posterior = _run_isolated_update(
            es,
            prior,
            responses,
            observations,
            [f"PARAM_{p}" for p in range(n_params)],
            {"random_seed": 42},
        )

        self._assert_snapshot(posterior, snapshot, "small_posterior_es.csv")
