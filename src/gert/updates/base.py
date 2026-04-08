"""Base classes for data assimilation updates."""

from abc import ABC, abstractmethod
from typing import Any

import polars as pl

from gert.experiments.models import ParameterMetadata
from gert.updates.spatial import SpatialToolkit


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
        parameters: pl.DataFrame,
        parameter_metadata: list[ParameterMetadata],
        simulated_responses: pl.DataFrame,
        observations: pl.DataFrame,
        toolkit: SpatialToolkit,
        algorithm_arguments: dict[str, Any],
    ) -> pl.DataFrame:
        """Performs the data assimilation update for a single iteration.

        Args:
            parameters: The pure numerical ensemble state matrix.
                        Rows are realizations, columns are parameter keys.
            parameter_metadata: List of ParameterMetadata descriptors mapping the
                                parameters columns to logical parameters and grids.
            simulated_responses: A Tidy DataFrame of simulated responses.
            observations: A DataFrame containing the observed values and their
                          standard deviations.
            toolkit: The SpatialToolkit engine for topological calculations.
            algorithm_arguments: A dictionary of custom settings
                                 for the algorithm.

        Returns:
            A DataFrame containing the updated state matrix for the next iteration.
        """
