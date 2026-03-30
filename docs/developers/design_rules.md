# GERT Design Rules

This document outlines the core architectural constraints and design rules that govern the Generic Ensemble Reservoir Tool (GERT). All contributions must adhere to these boundaries.

### Rule 1: Strict Domain Agnosticism in Core Data Models
* **Statement:** Internal data structures (`Parameters`, `Responses`, `Observations`) must remain completely generic (e.g., 1D/2D/3D tensors, numeric scalars, or untyped JSON schemas).
* **Explanation:** GERT must contain zero reservoir-specific nomenclature (no `SummaryConfig`, `GenDataConfig`, etc.). Any domain translation must happen outside the core tool.

### Rule 2: Immutability of Experiment Configuration
* **Statement:** Once an experiment is initialized, its configuration object becomes a strictly immutable artifact.
* **Explanation:** The configuration serves as the absolute source of truth for reproducible runs. It permanently embeds the exact initial Parameter Matrix used, and is never updated with posterior results during execution.

### Rule 3: Separation of Prior Sampling from Execution
* **Statement:** The core execution engine (`gert.experiment_runner`) must never calculate or sample probability distributions itself.
* **Explanation:** The runner strictly consumes deterministic, pre-calculated `ParameterMatrix` objects. The generation of these matrices (via `probabilit` or user injection) must happen in an isolated `gert.parameters` module before execution begins.

### Rule 4: API-Driven Persistent Storage
* **Statement:** The temporary execution scratch space (realization workdirs) is strictly separated from permanent analytical storage.
* **Explanation:** The execution engine does not manage permanent files on disk. Instead, forward models (or post-run scripts) must push their data directly to the Data Ingestion API. The storage backend (`gert.storage`) isolates how that data is queued (`.jsonl`) and consolidated (Parquet).

### Rule 5: Abstraction of HPC / Compute Environments
* **Statement:** Orchestration components must never interact directly with specific cluster commands (like `sbatch`, `bsub`).
* **Explanation:** All parallel execution boundaries must be encapsulated behind `psij-python` (or a similar adapter interface), keeping GERT entirely agnostic of the underlying execution environment.

### Rule 6: Decoupling of Forward Models and Mathematical Updates
* **Statement:** The modules that orchestrate forward model steps (`gert.experiment_runner`) must be strictly isolated from mathematical assimilation algorithms (`gert.update`).
* **Explanation:** Execution does not know about math. The `gert.update` module operates strictly as a consumer of flattened matrices from the storage layer, interacting purely with external math libraries (e.g., `iterative_ensemble_smoother`).

### Rule 7: Unidirectional Dependency from Everest
* **Statement:** Everest acts strictly as an external, higher-level client.
* **Explanation:** GERT core modules must possess zero knowledge of Everest's existence or its optimization concepts (objective functions, output constraints). Everest translates its domain needs into standard GERT parameters/responses via the GERT API.

### Rule 8: Event-Driven State and Observability
* **Statement:** Experiment progress and realization state transitions (e.g., `RUNNING`, `FAILED`) must be propagated asynchronously via an event stream (e.g., WebSockets).
* **Explanation:** The system avoids synchronous blocking polling. The GUI and external monitors react to state changes emitted by the orchestration and storage layers in real-time.

### Rule 9: Ephemeral File-System Security
* **Statement:** Authentication and connection metadata must rely on the OS file-system permissions, and its lifecycle must be strictly managed.
* **Explanation:** Network ports and Bearer tokens are written to a restricted file (`chmod 600`). GERT must use strict signal handling to guarantee the deletion of this connection file upon graceful shutdown or fatal crash to prevent orphaned state.

### Rule 10: Isolation of Test Data Orchestration
* **Statement:** Test factories, mock data generators, and complex dummy objects must be strictly confined to test packages (e.g., `tests/factories/`).
* **Explanation:** Production code paths must never embed, import, or rely on test generation logic, ensuring a lightweight binary and strict separation of concerns.

### Rule 11: Fail Fast and Strict Input Validation
* **Statement:** The system must reject invalid inputs immediately and loudly at the outermost boundary. It must never silently sanitize, guess, or attempt to gracefully recover from malformed data.
* **Explanation:** If an API payload, observation set, or parameter matrix is incomplete, malformed, or mathematically invalid, GERT must raise a strict, terminal error immediately (typically via Pydantic validation). Do not let bad state propagate deeper into the execution or mathematical layers before failing.

### Rule 12: Dependency Injection via Immutable Configs
* **Statement:** Core orchestration classes (e.g., `ExperimentOrchestrator`) should prefer receiving an immutable base truth (like `ExperimentConfig`) in their `__init__` rather than accepting pre-instantiated, large dependency objects (like `StorageAPI` or `JobSubmitter`).
* **Explanation:** Passing the immutable configuration as the single source of truth allows the orchestrator to internally instantiate and manage its own dependencies (Storage, Workdir Managers, Job Submitters) based on the config. This reduces brittle boilerplate in the routing/API layers and guarantees that all internal services are perfectly synchronized with the exact same configuration state.

### Rule 13: Constructor Completeness (No Two-Phase Initialization)
* **Statement:** Objects must be fully initialized, valid, and ready for use immediately upon instantiation.
* **Explanation:** Avoid "two-phase" initialization methods (like `start_experiment()`). If an attribute (e.g., `execution_id`, `storage_api`) is required for an object's methods to function, it must be assigned or generated in `__init__`. This eliminates the anti-pattern of scattering defensive `if self.attr is None:` checks throughout downstream business logic.

### Rule 14: Separation of Data and Control
* Core data models must not contain control logic or environment-specific validation.
* Data models, such as ExperimentConfig, should represent the data and its constraints. Any logic that interacts with the execution environment, such as validating file paths or permissions, belongs in the control layer (e.g., the ). This separation ensures that the data models remain portable and that the backend can be modified without affecting the core data structures.
