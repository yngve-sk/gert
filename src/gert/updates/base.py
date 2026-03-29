"""Base classes for data assimilation updates."""

from abc import ABC, abstractmethod
from typing import Any

import polars as pl


class UpdateAlgorithm(ABC):
    """Abstract Base Class for all data assimilation update algorithms.

    Each algorithm is implemented as a plugin that inherits from this class.
    The core GERT engine discovers and runs these plugins based on the
    `update_schedule` in the experiment configuration.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """The unique identifier for this update algorithm (e.g., "esmda")."""

    @abstractmethod
    def perform_update(
        self,
        current_parameters: pl.DataFrame,
        simulated_responses: pl.DataFrame,
        observations: pl.DataFrame,
        updatable_parameter_keys: list[str],
        algorithm_arguments: dict[str, Any],
    ) -> pl.DataFrame:
        """Performs the data assimilation update for a single iteration.

        Args:
            current_parameters: A DataFrame of the full parameter set for the
                                current iteration. Rows are realizations,
                                columns are parameter keys.
            simulated_responses: A DataFrame of the consolidated simulated
                                 responses that have corresponding observations.
                                 Rows are realizations, columns are response keys.
            observations: A DataFrame containing the observed values and their
                          standard deviations. The columns align with
                          `simulated_responses`.
            updatable_parameter_keys: The specific list of parameter keys from
                                      `current_parameters` that the algorithm
                                      is permitted to modify.
            algorithm_arguments: A dict of custom settings for the algorithm.

        Returns:
            A DataFrame containing the complete, updated parameter matrix for the
            next iteration. The schema must be identical to `current_parameters`.
        """
