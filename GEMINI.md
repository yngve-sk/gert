# GERT Core Architectural Mandates

This file contains the foundational, non-negotiable rules for the Generic Ensemble Reservoir Tool (GERT). These rules apply to all code modifications and take precedence over general AI workflows.

## 1. Core Technologies
*   **DataFrames:** ALWAYS use `polars`. NEVER use `pandas`.
*   **Data Models:** ALWAYS use `pydantic.BaseModel` for structured state and configuration. NEVER use raw untyped dictionaries (`dict[str, Any]`).
*   **Serialization:** NEVER embed raw DataFrames (`pl.DataFrame`) directly inside Pydantic models intended for JSON serialization. Use `SkipJsonSchema` or URI references.
*   **Linting & Formatting:** ALWAYS use `ruff` (all rules enabled by default). Formatting is done via `ruff format`. Do not disable rules unless absolutely necessary (and leave an inline comment explaining why).
*   **Types:** ALWAYS use strict Python 3.10+ type hinting (`mypy --strict`). Avoid `Any`. No implicit returns.

## 2. Architectural Boundaries
*   **Domain Agnosticism:** Core models (`Parameters`, `Responses`, `Observations`) must remain mathematically generic. No reservoir-specific terminology.
*   **Separation of Concerns:**
    *   The `Orchestrator` (`gert.experiment_runner`) is "dumb"; it only routes data and manages process lifecycles via `psij`.
    *   The `Math Plugins` (`gert.update`) are "smart"; they interpret topologies (via `SpatialToolkit`) and perform Data Assimilation.
    *   The `Storage API` (`gert.storage`) isolates all file I/O, queuing, and Parquet consolidation.
*   **Immutability:** `ExperimentConfig` is an immutable artifact once initialized. Use dependency injection (pass initialized services or configs, not large uninitialized objects).
*   **Fail Fast:** Validate inputs strictly at boundaries. Do not silently sanitize or recover from malformed data.

## 3. Testing
*   **Framework:** Use `pytest`. Tests must be stateless.
*   **Mocks:** Keep all mock data generators in `tests/factories/` or `conftest.py`. Never in `src/gert/`.
*   **Unit Testability:** Isolate I/O from logic (Functional Core, Imperative Shell).

*Note: For deep implementation details regarding specific algorithms, TUI monitoring, or overarching system design, activate the relevant specialized skills (`gert-architect`, `gert-enif`, `gert-tui`, etc.).*
