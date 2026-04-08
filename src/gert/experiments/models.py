"""Core immutable data models for GERT experiments."""

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Self

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, model_validator
from pydantic.json_schema import SkipJsonSchema


class GridMetadata(BaseModel):
    """Configuration for a spatial grid arena."""

    id: str  # e.g., "main_reservoir_grid"
    shape: tuple[int, ...]  # The bounding box (e.g., (Nx, Ny, Nz))

    # Internal server-side storage of coordinates.
    # For a 3D grid, this DataFrame has columns ['i', 'j', 'k'].
    # We use a private attribute to avoid serialization issues as per docs.
    _coordinates: pl.DataFrame | None = None


class ParameterMetadata(BaseModel):
    """Lightweight descriptor mapping flat parameter to logical parameters."""

    name: str = Field(
        ...,
        description=("The logical base name of the parameter (e.g., 'PERM')."),
    )
    columns: list[str] = Field(
        ...,
        description=("The exact list of corresponding column keys in the parameter."),
    )
    grid_id: str | None = Field(
        default=None,
        description=(
            "Pointer to the GridMetadata. None if the parameter is a global scalar."
        ),
    )


class ParameterConfig(BaseModel):
    """Metadata describing a parameter's properties across the entire ensemble."""

    source: str | None = None
    tags: list[str] = Field(default_factory=list)
    # Controls if this parameter enters the mathematical update vector.
    updatable: bool = True


class FileReference(BaseModel):
    """A pointer to an external file.

    Paths may include a '{realization}' template if the data is split by realization.
    """

    path: str
    format: str = "parquet"


class ParameterDataset(BaseModel):
    """Configuration for out-of-core parameters (e.g., 2D/3D grids).

    Assumes a 'Tidy' format: One row per coordinate/index, one column per parameter.
    If the file is not realization-split, it is expected to have a 'realization' column.
    """

    reference: FileReference
    # The columns in the file that should be treated as parameters.
    parameters: list[str]
    # The columns used for spatial/logical indexing
    # (e.g., ['i', 'j', 'k'] or ['cell_id']).
    index_columns: list[str] = Field(default_factory=list)


# Sparse inline data: Maps realization ID to a scalar value.
# Restricted to scalar values per realization for JSON simplicity. Massive
# 2D/3D fields should be provided out-of-core via ParameterDataset.
type ParameterPayload = dict[int, float | int | str | bool]


class ParameterMatrix(BaseModel):
    """The deterministic, ensemble-wide prior parameter matrix."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Metadata keyed by parameter name.
    metadata: dict[str, ParameterConfig] = Field(default_factory=dict)

    # 1. Inline Sparse Data pr realization (for scalars)
    # values["MULTFLT"] = {0: 1.1, 1: 1.2, 5: 1.3, ...}
    values: dict[str, ParameterPayload] = Field(default_factory=dict)

    # 2. Out-of-core Datasets (for massive grids and full sheets) pr realization
    # Used for tidy Parquet files containing spatial fields.
    datasets: list[ParameterDataset] = Field(default_factory=list)

    # 3. Optional pre-computed or posterior DataFrame
    dataframe: Annotated[pl.DataFrame | None, SkipJsonSchema()] = Field(
        default=None,
        exclude=True,
    )

    def get_realizations(self, base_working_directory: Path | None = None) -> set[int]:
        """Get the set of all realization IDs in this parameter matrix.

        Args:
            base_working_directory: Optional base path for resolving dataset paths.

        Returns:
            A set of integer realization IDs.

        Raises:
            FileNotFoundError: If referenced datasets do not exist.
        """
        if self.dataframe is not None:
            return set(self.dataframe["realization"].to_list())

        realizations: set[int] = set()
        if self.values:
            for val_dict in self.values.values():
                realizations.update(val_dict.keys())

        if self.datasets:
            for dataset in self.datasets:
                path_str = dataset.reference.path
                source_path = Path(path_str)
                if not source_path.is_absolute():
                    base_dir = base_working_directory or Path.cwd()
                    source_path = (base_dir / source_path).resolve()

                if source_path.exists():
                    # Read just the realization column to be efficient
                    # if it exists. We load the schema first.
                    schema = pl.read_parquet_schema(source_path)
                    if "realization" in schema:
                        df = (
                            pl.scan_parquet(source_path)
                            .select("realization")
                            .unique()
                            .collect()
                        )
                        realizations.update(df["realization"].to_list())
                else:
                    msg = f"Dataset file not found: {source_path}"
                    raise FileNotFoundError(msg)

        return realizations

    def to_df(self, base_working_directory: Path | None = None) -> pl.DataFrame:
        """Convert ParameterMatrix to a Wide DataFrame.

        Returns:
            A Polars DataFrame where rows are realizations.
        """
        if self.dataframe is not None:
            return self.dataframe

        # Collect all realization IDs and load dataset DataFrames
        realizations, dataset_dfs = self._get_dataset_dfs(base_working_directory)

        for val_dict in self.values.values():
            realizations.update(val_dict.keys())

        if not realizations:
            return pl.DataFrame({"realization": []})

        # Build initial DataFrame from inline values
        rows = []
        for r_id in sorted(realizations):
            row: dict[str, Any] = {"realization": r_id}
            for key, val_dict in self.values.items():
                if r_id in val_dict:
                    row[key] = val_dict[r_id]
            rows.append(row)

        df = pl.DataFrame(rows)

        # Merge in the dataset fields
        return self._merge_datasets(df, dataset_dfs)

    def _get_dataset_dfs(
        self,
        base_working_directory: Path | None,
    ) -> tuple[set[int], list[tuple[ParameterDataset, pl.DataFrame]]]:
        """Load DataFrames for all datasets and collect realization IDs."""
        realizations: set[int] = set()
        dataset_dfs: list[tuple[ParameterDataset, pl.DataFrame]] = []

        for dataset in self.datasets:
            path_str = dataset.reference.path
            source_path = Path(path_str)
            if not source_path.is_absolute():
                base_dir = base_working_directory or Path.cwd()
                source_path = (base_dir / source_path).resolve()

            if source_path.exists():
                df = pl.read_parquet(source_path)
                if "realization" in df.columns:
                    realizations.update(df["realization"].unique().to_list())
                dataset_dfs.append((dataset, df))

        return realizations, dataset_dfs

    def _merge_datasets(
        self,
        df: pl.DataFrame,
        dataset_dfs: list[tuple[ParameterDataset, pl.DataFrame]],
    ) -> pl.DataFrame:
        """Merge loaded dataset DataFrames into the main DataFrame."""
        result_df = df
        for dataset, ds_df in dataset_dfs:
            if dataset.index_columns:
                ds_df = ds_df.sort(["realization", *dataset.index_columns])

                # Group by realization and aggregate parameters into Lists
                agg_exprs = [pl.col(p) for p in dataset.parameters]
                grouped = ds_df.group_by("realization", maintain_order=True).agg(
                    agg_exprs,
                )

                result_df = result_df.join(grouped, on="realization", how="left")
            else:
                # Just join directly
                result_df = result_df.join(
                    ds_df.select(["realization", *dataset.parameters]),
                    on="realization",
                    how="left",
                )
        return result_df

    def replace_values_from_df(self, df: pl.DataFrame) -> Self:
        """Create a new ParameterMatrix representing the state in the DataFrame.

        Preserves metadata and out-of-core dataset references.

        Args:
            df: A Polars DataFrame containing updated parameter values, where each row
                corresponds to a realization and each column to a parameter.

        Returns:
            A new ParameterMatrix instance.
        """
        # We don't want to convert massive grids back into inline dictionaries.
        # So we just store the DataFrame directly.
        return type(
            self,
        )(
            metadata=self.metadata,
            values=self.values,  # Defer to dataframe for actual values
            datasets=self.datasets,
            dataframe=df,
        )


class Observation(BaseModel):
    """A single mathematical observation.

    Fundamentally requires a measurement value and a standard deviation/error.
    The key is a strict mapping of string identifiers
    (e.g., {"response": "FOPR", "time": "2024"}).
    """

    key: dict[str, str]
    value: float
    std_dev: PositiveFloat
    coordinates: dict[str, float] | None = None

    @model_validator(mode="after")
    def validate_key_contains_response(self) -> Self:
        """Ensure that the key dictionary always contains a 'response' identifier.

        Raises:
            ValueError: If the 'response' key is not present.
        """
        if "response" not in self.key:
            msg = (
                "The 'key' dictionary must contain a 'response' identifier "
                "(e.g., {'response': 'FOPR', 'time': '10'})."
            )
            raise ValueError(msg)
        return self


class HookEvent(StrEnum):
    """Lifecycle points for external script execution."""

    PRE_EXPERIMENT = "pre_experiment"
    POST_EXPERIMENT = "post_experiment"
    PRE_FORWARD_MODEL = "pre_forward_model"
    POST_FORWARD_MODEL = "post_forward_model"
    PRE_UPDATE = "pre_update"
    POST_UPDATE = "post_update"


class ExecutableHook(BaseModel):
    """An external CLI script triggered by an event."""

    name: str
    event: HookEvent
    iterations: list[int] | None = None
    executable: str
    args: list[str] = Field(default_factory=list)


class PluginHook(BaseModel):
    """An externally installed GERT
    lifecycle hook triggered at a given lifecycle point."""

    name: str
    event: HookEvent
    iterations: list[int] | None = None
    uses: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ExecutableForwardModelStep(BaseModel):
    """An executable CLI step in the forward model sequence.

    Strictly defines the data contract (inputs/outputs) for this specific executable.
    """

    name: str
    executable: str
    args: list[str] = Field(default_factory=list)
    consumed_parameters: list[str] = Field(default_factory=list)
    expected_responses: list[str] = Field(default_factory=list)


class PluginForwardModelStep(BaseModel):
    """A plugin-based step in the forward model sequence."""

    name: str
    uses: str
    arguments: dict[str, str] = Field(default_factory=dict)


class QueueConfig(BaseModel):
    """Configuration for the HPC/Job scheduler."""

    backend: str = "local"
    walltime: int | None = None
    custom_attributes: dict[str, Any] = Field(default_factory=dict)


class RealizationWorkdirFile(BaseModel):
    """A static file or directory to be injected into the realization's
    execution workdir.
    """

    source: str
    target: str | None = None  # If None, defaults to the source's basename


class Template(BaseModel):
    """A text template rendered into the realization's workdir.

    Uses standard engines (like Jinja2) to replace variables (e.g., `{{ MULTFLT }}`)
    with the current realization's parameter values.
    """

    target: str
    # Template can be read from an external file or provided inline as a string.
    source: str | None = None
    content: str | None = None

    engine: str = "jinja2"

    @model_validator(mode="after")
    def validate_source_or_content(self) -> Self:
        if bool(self.source) == bool(self.content):
            msg = "Template must provide exactly one of 'source' or 'content'."
            raise ValueError(
                msg,
            )
        return self


class UpdateStep(BaseModel):
    """Configuration for a single mathematical update step."""

    name: str
    algorithm: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    # The specific parameters to update in this step.
    # If empty, all updatable parameters from the matrix are used.
    updatable_parameters: list[str] = Field(default_factory=list)


class ObservationDetail(BaseModel):
    """Detailed observation mismatch statistics for a specific observation."""

    response: str | None = None
    key: dict[str, str] = Field(default_factory=dict)
    absolute_residual: float
    normalized_misfit: float
    absolute_misfit: float


class ObservationSummary(BaseModel):
    """Summary of observation mismatches across an iteration."""

    average_absolute_residual: float
    average_normalized_misfit: float
    average_absolute_misfit: float
    details: list[ObservationDetail]


class UpdateMetadata(BaseModel):
    """The schema for a mathematical update step."""

    status: str
    algorithm_name: str
    configuration: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    duration_seconds: float | None = None
    start_time: str | None = None
    end_time: str | None = None


class ExperimentConfig(BaseModel):
    """Immutable root configuration for a GERT experiment."""

    name: str
    base_working_directory: Path

    storage_base: Path = Field(default_factory=lambda: Path("./permanent_storage"))
    realization_workdirs_base: Path = Field(
        default_factory=lambda: Path("./workdirs"),
    )
    consolidation_interval: float = Field(
        default=5.0,
        description="Interval in seconds for background consolidation",
    )

    workdir_files: list[RealizationWorkdirFile] = Field(default_factory=list)
    templates: list[Template] = Field(default_factory=list)
    forward_model_steps: list[ExecutableForwardModelStep | PluginForwardModelStep]
    lifecycle_hooks: list[ExecutableHook | PluginHook] = Field(default_factory=list)
    updates: list[UpdateStep] = Field(default_factory=list)
    queue_config: QueueConfig
    parameter_matrix: ParameterMatrix
    observations: list[Observation]

    @model_validator(mode="after")
    def resolve_paths(self) -> Self:
        """Resolve storage and workdir paths relative to base_working_directory."""
        if not self.storage_base.is_absolute():
            self.storage_base = (
                self.base_working_directory / self.storage_base
            ).resolve()
        if not self.realization_workdirs_base.is_absolute():
            self.realization_workdirs_base = (
                self.base_working_directory / self.realization_workdirs_base
            ).resolve()
        return self

    @property
    def num_iterations(self) -> int:
        """Return the total number of iterations (Prior + N updates)."""
        return len(self.updates) + 1

    @property
    def num_realizations(self) -> int:
        """Return the total number of realizations in the ensemble."""
        return len(self.parameter_matrix.get_realizations(self.base_working_directory))

    @property
    def num_fm_steps(self) -> int:
        """Return the number of forward model steps."""
        return len(self.forward_model_steps)

    @property
    def step_names(self) -> list[str]:
        """Return the names of the forward model steps."""
        return [s.name for s in self.forward_model_steps]

    @property
    def num_observations(self) -> int:
        """Return the total number of observations."""
        return len(self.observations)

    @property
    def num_parameters(self) -> int:
        """Return the total number of parameters."""
        return len(self.parameter_matrix.metadata)


class ExecutionState(BaseModel):
    """Overall state of an experiment execution."""

    experiment_id: str
    execution_id: str
    status: str
    current_iteration: int = 0
    active_job_ids: list[str] = Field(default_factory=list)
    active_realizations: list[int] = Field(default_factory=list)
    completed_realizations: list[int] = Field(default_factory=list)
    failed_realizations: list[int] = Field(default_factory=list)
    error: str | None = None


class ResponsePayload(BaseModel):
    """Schema for simulated responses pushed back to GERT by forward models.

    These values represent the simulated values
    (sometimes corresponding to physical observations).
    """

    realization: int
    source_step: str
    key: dict[str, str]
    value: float

    @model_validator(mode="after")
    def validate_key_contains_response(self) -> Self:
        """Ensure that the key dictionary always contains a 'response' identifier.

        Raises:
            ValueError: If the 'response' key is not present.
        """
        if "response" not in self.key:
            msg = (
                "The 'key' dictionary must contain a 'response' identifier "
                "(e.g., {'response': 'FOPR', 'time': '10'})."
            )
            raise ValueError(msg)
        return self


class InlineParameterIngestionPayload(BaseModel):
    """Schema for calculated inline parameters dynamically pushed back to GERT.

    Used when a forward model step (e.g., a pre-processor) generates new
    scalar values (floats, strings, etc.) that should be tracked alongside priors.
    """

    realization: int
    source_step: str
    key: dict[str, str]
    value: float | int | str | bool


class FileParameterIngestionPayload(BaseModel):
    """Schema for parameters dynamically pushed back to GERT.

    Used when a forward model step generates entirely new fields or grids
    saved to disk, passing a FileReference back instead of raw data.
    """

    realization: int
    source_step: str
    key: str | dict[str, str]
    value: FileReference


type IngestionPayload = (
    ResponsePayload | InlineParameterIngestionPayload | FileParameterIngestionPayload
)
