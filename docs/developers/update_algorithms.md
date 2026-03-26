# GERT Design Specification: Update Algorithm Plugins

This document defines the plugin architecture for data assimilation algorithms in GERT. It establishes the common interface that all update algorithms must adhere to and provides the initial scaffolding for core implementations.

## Conceptual Clarification: Update Step vs. Experiment Workflow

It is important to note that algorithms like **IES (Iterative Ensemble Smoother)** or **ES-MDA (Ensemble Smoother with Multiple Data Assimilation)** are not single plugins in the GERT architecture. These represent the *entire experiment workflow*.

An `UpdateAlgorithm` plugin in GERT is strictly responsible for performing a **single mathematical assimilation step** (e.g., one Kalman update with or without error inflation). The iterative nature of an experiment (like ES-MDA) is achieved by the orchestrator scheduling this single-step plugin multiple times via the experiment configuration's `update_schedule`, passing different arguments (such as a varying `alpha` inflation factor) to the plugin at each iteration.

## 1. The `UpdateAlgorithm` Interface (ABC)

To ensure that any assimilation algorithm can be seamlessly integrated into the `ExperimentOrchestrator`, all plugins must inherit from the `UpdateAlgorithm` abstract base class. This enforces a consistent contract for how the orchestrator provides data to the algorithm and receives the updated parameters.

This interface will be located in a new file, `gert/updates/base.py`.

**File:** `gert/updates/base.py`
```python
from abc import ABC, abstractmethod
from typing import Any

import polars as pl


class UpdateAlgorithm(ABC):
    """Abstract Base Class for all data assimilation update algorithms.

    Each algorithm is implemented as a plugin that inherits from this class.
    The core GERT engine discovers and runs these plugins based on the
    `update_schedule` in the experiment configuration.

    Dependencies required by a specific algorithm (e.g., `scipy`, `numpy`)
    should be managed as optional dependencies for that plugin, keeping the
    GERT core installation lightweight.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """The unique identifier for this update algorithm (e.g., "kalman_update")."""

    @abstractmethod
    def perform_update(
        self,
        current_parameters: pl.DataFrame,
        simulated_responses: pl.DataFrame,
        observations: pl.DataFrame,
        updatable_parameter_keys: list[str],
        algorithm_arguments: dict[str, Any],
    ) -> pl.DataFrame:
        """
        Performs the data assimilation update for a single iteration.

        Args:
            current_parameters: A DataFrame of the full parameter set for the
                                current iteration. Rows are realizations,
                                columns are parameter keys.
            simulated_responses: A DataFrame of the consolidated simulated
                                 responses that have corresponding observations.
                                 Rows are realizations, columns are response keys.
                                 The data is aligned with `observations`.
            observations: A DataFrame containing the observed values and their
                          standard deviations. The columns align with
                          `simulated_responses`.
            updatable_parameter_keys: The specific list of parameter keys from
                                      `current_parameters` that the algorithm
                                      is permitted to modify. This is derived
                                      from the `updatable_parameters` tags in
                                      the `UpdateStep` config.
            algorithm_arguments: A dict of custom settings for the algorithm,
                                 taken directly from the `UpdateStep`
                                 configuration (e.g., `{"alpha": 4.0}`).

        Returns:
            A DataFrame containing the complete, updated parameter matrix for the
            next iteration. The schema must be identical to `current_parameters`.
            Parameters not in `updatable_parameter_keys` must be returned
            unmodified.
        """
        pass
```

## 2. Core Plugin Implementations

GERT will ship with a set of standard, well-tested single-step update algorithms. These will reside in a new `gert.plugins` namespace. Below is an initial scaffold for a standard Kalman update step that optionally accepts an inflation factor to support workflows like ES-MDA.

**File:** `gert/plugins/kalman.py`
```python
from typing import Any

import polars as pl

from gert.updates.base import UpdateAlgorithm


class KalmanUpdateStep(UpdateAlgorithm):
    """An implementation of a single-step Kalman update.

    This algorithm performs a single global update based on all observations.
    If the 'alpha' argument is provided and is > 1.0, it inflates the
    observation errors (standard deviations) by sqrt(alpha) before the update,
    which is necessary for iterative workflows like ES-MDA.

    Expected optional `algorithm_arguments`:
        - `alpha` (float): The inflation coefficient. Default is 1.0.
    """

    @property
    def name(self) -> str:
        return "kalman_update"

    def perform_update(
        self,
        current_parameters: pl.DataFrame,
        simulated_responses: pl.DataFrame,
        observations: pl.DataFrame,
        updatable_parameter_keys: list[str],
        algorithm_arguments: dict[str, Any],
    ) -> pl.DataFrame:
        # TODO: Implement the single-step Kalman update equation.
        # 1. Check for 'alpha' in algorithm_arguments (default to 1.0).
        # 2. If alpha > 1.0, inflate the standard deviations in the
        #    `observations` DataFrame by sqrt(alpha).
        # 3. Compute covariance matrices from the DataFrames.
        # 4. Apply the Kalman gain formula.
        # 5. Update the `updatable_parameter_keys` in a new DataFrame.
        # 6. Return the new, complete parameter DataFrame.
        pass
```

## 3. Plugin Registration and Discovery (Internal & External)

GERT uses the `pluggy` framework to manage both its internal core algorithms and any third-party plugins installed in the environment. This ensures that custom mathematical updates can be integrated without modifying the GERT codebase.

To make an algorithm discoverable, it must be registered through the `gert_update_algorithms` hook. This is analogous to how forward model steps and lifecycle hooks are managed.

### The Registration Hook

The orchestration engine expects a list of `UpdateAlgorithm` instances from the `gert_update_algorithms` hook.

**File:** `src/gert/plugins/plugins.py` (Extended)
```python
class GertPluginSpecs:
    # ... existing hooks ...

    @pluggy.HookspecMarker("gert")
    def gert_update_algorithms(self) -> list[UpdateAlgorithm]:
        """Discover and load external update algorithm plugins."""
        return []
```

### Implementing an External Plugin

A developer creating a new update algorithm (e.g., in a package called `gert_math_pro`) would implement the hook as follows:

**File:** `gert_math_pro/registration.py`
```python
from gert.plugins.plugins import gert_plugin
from gert.updates.base import UpdateAlgorithm
from .algo import LocalizedKalmanUpdate

@gert_plugin
def gert_update_algorithms() -> list[UpdateAlgorithm]:
    return [LocalizedKalmanUpdate()]
```

### Registration via Entry Points

For GERT to find the plugin automatically, it must be declared as a `gert` entry point in the plugin package's `pyproject.toml`:

```toml
[project.entry-points."gert"]
math_pro = "gert_math_pro.registration"
```

## 4. Execution Workflow

The GERT `ExperimentOrchestrator` uses the `algorithm` field from the `UpdateStep` configuration to dynamically load and instantiate the correct plugin at runtime.

To run an **ES-MDA** workflow, the experiment configuration would schedule the *same* `kalman_update` plugin multiple times with different `alpha` values.

For example, a configuration of:
```yaml
update_schedule:
  - name: "MDA_Step_1"
    algorithm: "kalman_update" # Matches the .name property of the plugin
    arguments:
      alpha: 4.0
  - name: "MDA_Step_2"
    algorithm: "kalman_update"
    arguments:
      alpha: 2.0
  - name: "MDA_Step_3"
    algorithm: "kalman_update"
    arguments:
      alpha: 1.33
```

This tells the orchestrator to execute the math of `kalman_update` three times iteratively. This makes the system fully extensible to user-defined algorithms while keeping the orchestration and mathematics clearly decoupled.


## 5. Testing Strategy: Update Algorithm Plugins

This document outlines the testing philosophy and requirements for all Data Assimilation (DA) update algorithms in GERT.

Because GERT update algorithms (e.g., ES, EnIF, Localized ES) are implemented as isolated plugins conforming to the `UpdateAlgorithm` ABC, they must be tested in strict isolation. We do not run the forward simulator or the `ExperimentOrchestrator` to test the math. Instead, we pass constructed prior, response, and observation DataFrames directly to the plugin's `perform_update` method and assert against the returned posterior DataFrame.

### 1. Core Testing Principles

*   **Fix Random Seeds:** DA algorithms rely heavily on random observation perturbations. Every test must explicitly pass a `random_seed` in the `algorithm_arguments` to ensure deterministic, reproducible results across CI/CD runs.
*   **Test the Contract, Not Just the Math:** Ensure the plugin respects the `UpdateAlgorithm` interface.
    *   Does it return a Polars DataFrame with the exact same schema/columns as the input?
    *   Does it leave parameters not in `updatable_parameter_keys` strictly untouched?
*   **Type and Shape Safety:** Ensure the algorithm handles edge cases in matrix reshaping (e.g., $1 \times N$, $N \times 1$) without throwing broadcast errors.

### 2. Mathematical Sanity Checks

Every update algorithm must pass the following fundamental DA sanity checks.

#### A. Variance Reduction

The defining characteristic of an information filter or Kalman update is that assimilating data reduces uncertainty.

*   **Assertion:** The standard deviation (or variance) of the ensemble for any updated parameter must be less than or equal to its prior standard deviation.
*   **Note:** With very small ensembles or extreme noise, sampling error can occasionally cause slight variance increases, so this test should be run with a sufficiently large ensemble ($N > 100$) or a relaxed tolerance.

#### B. Mean Shift (Pull to Truth)

The ensemble mean should move toward a state that better explains the observations.

*   **Assertion:** Create a prior biased heavily away from an observation. After the update, the absolute difference between the prior mean and the "true" parameter value should be greater than the absolute difference between the posterior mean and the "true" parameter value.

#### C. The "Zero-Information" Update

If the observation errors ($\sigma$) are set to near-infinity (or inflation $\alpha$ is massive), the update should ignore the observations.

*   **Assertion:** The posterior parameters should be virtually identical to the prior parameters.

### 3. Test Case Sizing and Design

To thoroughly test the algorithms, tests should be tiered by dimensionality.

#### The "Micro" Case (Debugging & Shape validation)
*   **Dimensions:** 1 Parameter, 1 Observation, 2 Realizations.
*   **Purpose:** This is the absolute smallest valid matrix size. It guarantees your algorithm doesn't accidentally collapse 2D arrays into 1D arrays or hardcode expected dimensionalities. It is also small enough that you can calculate the expected posterior by hand on a piece of paper and assert against exact floats.

#### The "Standard" Case (Covariance validation)
*   **Dimensions:** 3-5 Parameters, 2-3 Observations, 50-100 Realizations.
*   **Purpose:** This tests cross-covariances. Set up the prior such that Parameter A and Parameter B are strongly correlated. Observe only a response related to Parameter A.
*   **Assertion:** Parameter B must also update, proving that the algorithm correctly applies the covariance matrix to unobserved variables.

#### The "Over-determined" Case (Subspace inversion check)
*   **Dimensions:** 5 Parameters, 50 Observations, 10 Realizations.
*   **Purpose:** In many algorithms, if $N_{obs} > N_{realizations}$, standard matrix inversion will fail due to singularity.
*   **Assertion:** The algorithm must complete successfully, proving it correctly implements subspace inversion (Truncated SVD) or pseudo-inverses.

### 4. Edge Cases to Cover

*   **Ensemble Collapse:** Feed the algorithm a prior where every single realization has the exact same value (variance = 0). The algorithm should either raise a specific, handled error, or return the prior cleanly without crashing due to a divide-by-zero error.
*   **Missing Observations:** Pass an observation DataFrame containing NaN or null values. The algorithm must handle this gracefully (typically by dropping that observation from the state vector).
*   **Missing Realizations:** Pass simulated responses where one realization failed (contains NaN). The algorithm must drop that realization from the update math and return the DataFrame cleanly.
*   **Localization Matrix (Rho) Mismatches:** For localized algorithms, pass a rho matrix in `algorithm_arguments` that has the wrong shape (e.g., $N_{params} \times (N_{obs} + 1)$). It should raise a clear ValueError.

### 5. Snapshot (Regression) Testing Strategy
While behavioral tests (verifying variance reduction, mean shifts) prove that the algorithm works mathematically, snapshot testing proves that the algorithm hasn't accidentally changed during a code refactor.

Because data assimilation involves complex linear algebra (e.g., SVD, Cholesky decompositions, pseudo-inverses), even a seemingly harmless refactor can introduce silent numerical regressions. Snapshots act as a "gold standard" freeze of the algorithm's output.

The "Two-Snapshot" Rule
For every UpdateAlgorithm plugin, you must implement exactly two snapshot tests:

The Small/Dummy Snapshot:

Scope: 2-3 Parameters, 1-2 Observations, 5-10 Realizations.

Purpose: If this snapshot fails, the matrices are small enough that a developer can manually trace the linear algebra to find exactly where the math diverged.

The Comprehensive/Large Snapshot:

Scope: "Standard Case" sizing (e.g., 50 parameters, 100 observations, 100 realizations).

Purpose: Ensures that complex matrix interactions—such as subspace inversion truncations, overlapping localization matrices, and large cross-covariances—do not drift or break when dependencies are updated.

Using pytest-snapshot Safely with Floating-Point Math
We use the pytest-snapshot library to manage our regression files.

CRITICAL WARNING: Low-level C/Fortran solvers calculate the 14th decimal place slightly differently depending on the CPU architecture (x86 vs. ARM) and OS. Because pytest-snapshot performs exact string matching, comparing raw CSV outputs will cause CI pipelines to fail randomly.

The Standard: Before passing a Polars DataFrame to snapshot.assert_match(), you must round all floating-point columns to a hardware-safe precision (5 decimal places).

Example Implementation
```Python
import polars as pl
from gert.plugins.kalman import KalmanUpdateStep

def test_es_update_comprehensive_snapshot(snapshot):
    # 1. Load the fixed inputs
    prior = pl.read_parquet("tests/fixtures/standard_prior.parquet")
    responses = pl.read_parquet("tests/fixtures/standard_responses.parquet")
    observations = pl.read_parquet("tests/fixtures/standard_obs.parquet")

    # 2. Run the plugin (CRITICAL: Fix the random_seed!)
    plugin = KalmanUpdateStep()
    posterior = plugin.perform_update(
        current_parameters=prior,
        simulated_responses=responses,
        observations=observations,
        updatable_parameter_keys=["PORO", "PERM", "MULT_Z"],
        algorithm_arguments={"alpha": 1.0, "random_seed": 42}
    )

    # 3. Round floating-point columns to prevent cross-platform hardware drift
    rounded_posterior = posterior.select(
        pl.all().exclude(pl.Float64, pl.Float32),
        pl.col(pl.Float64, pl.Float32).round(5)
    )

    # 4. Assert against the snapshot (use `pytest --snapshot-update` to generate/update)
    snapshot.assert_match(
        rounded_posterior.write_csv(),
        'standard_posterior_es.csv'
    )
```
