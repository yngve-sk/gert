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
