"""Core immutable data models for GERT experiments."""

from enum import Enum
from pathlib import Path
from typing import Any, TypeAlias

from pydantic import BaseModel, Field, PositiveFloat, model_validator
from typing_extensions import Self


class ParameterMetadata(BaseModel):
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
ParameterPayload: TypeAlias = dict[int, float | int | str | bool]


class ParameterMatrix(BaseModel):
    """The deterministic, ensemble-wide prior parameter matrix."""

    # Metadata keyed by parameter name.
    metadata: dict[str, ParameterMetadata] = Field(default_factory=dict)

    # 1. Inline Sparse Data pr realization (for scalars)
    # values["MULTFLT"] = {0: 1.1, 1: 1.2, 5: 1.3, ...}
    values: dict[str, ParameterPayload] = Field(default_factory=dict)

    # 2. Out-of-core Datasets (for massive grids and full sheets) pr realization
    # Used for tidy Parquet files containing spatial fields.
    datasets: list[ParameterDataset] = Field(default_factory=list)


class Observation(BaseModel):
    """A single mathematical observation.

    Fundamentally requires a measurement value and a standard deviation/error.
    The key is a strict mapping of string identifiers
    (e.g., {"response": "FOPR", "time": "2024"}).
    """

    key: dict[str, str]
    value: float
    std_dev: PositiveFloat


class HookEvent(str, Enum):
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


class ExperimentConfig(BaseModel):
    """Immutable root configuration for a GERT experiment."""

    name: str
    base_working_directory: Path

    storage_base: Path = Field(default_factory=lambda: Path("./gert_storage"))
    realization_workdirs_base: Path = Field(
        default_factory=lambda: Path("./gert_storage/workdirs"),
    )
    consolidation_interval: float = Field(
        default=5.0,
        description="Interval in seconds for background consolidation",
    )

    workdir_files: list[RealizationWorkdirFile] = Field(default_factory=list)
    templates: list[Template] = Field(default_factory=list)
    forward_model_steps: list[ExecutableForwardModelStep | PluginForwardModelStep]
    lifecycle_hooks: list[ExecutableHook | PluginHook] = Field(default_factory=list)
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


class ResponsePayload(BaseModel):
    """Schema for simulated responses pushed back to GERT by forward models.

    These values represent the simulated values
    (sometimes corresponding to physical observations).
    """

    realization: int
    source_step: str
    key: dict[str, str]
    value: float


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


IngestionPayload: TypeAlias = (
    ResponsePayload | InlineParameterIngestionPayload | FileParameterIngestionPayload
)
