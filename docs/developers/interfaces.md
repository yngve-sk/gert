# GERT Interfaces and Module Organization

This document defines the core Python modules and abstract interfaces for the Generic Ensemble Reservoir Tool (GERT). Developers and AI assistants must strictly adhere to these boundaries to maintain the decoupled, generic architecture.

---

## 1. `gert.experiments` (Core Data Structures & Immutable State)
This module contains the strictly defined, domain-agnostic Pydantic models (or dataclasses) that represent the data at rest. These objects are purely data; they contain no execution or control logic, though they may contain pure data transformation methods (e.g., `to_df()`) to provide alternative representations.

* **`ExperimentConfig`**: The root immutable artifact. Contains the forward model steps, queue configurations, and a hard link to the initial `ParameterMatrix`.
* **`ParameterMatrix`**: A 2D deterministic dataset representing the exact values to inject into realizations.
* **`ObservationSet`**: A collection of expected responses mapped to physical/synthetic truth, fundamentally requiring `value`, `std_dev`, and a `key` dict. **Rule:** The `key` dict must *always* contain a `"response"` attribute (e.g., `{"response": "FOPR", "well": "W1"}`). For 1D/time-series data, `"response"` is the variable name (like `FOPR`). For nD data, `"response"` is the dataset name, and further details are given by `x, y, z`, etc.
* **`IngestionPayload`**: The generic JSON schema expected from forward models (e.g., `{"realization": 42, "source_step": "sim", "key": {"response": "FOPR"}, "value": 100.0}`).
* **`UpdateMetadata`**: The schema capturing the state and configuration of a mathematical update step (`status`, `algorithm`, `configuration`, `metrics` like prior/posterior variance, `error`, `duration`).
* **`ObservationSummary`**: The schema capturing the aggregate statistics on how responses and observations deviate. Computes the `average_absolute_residual`, the bounded `average_normalized_residual` (-1, 1), and `average_absolute_misfit`.

---

## 2. `gert.storage` (Data Ingestion & Analytical Storage)
This module isolates all high-throughput disk I/O, message queuing, and Parquet consolidation. It does not know about jobs or clusters.

* **`IngestionReceiver` (Interface)**
    * `push_data(experiment_id: str, execution_id: str, payload: IngestionPayload) -> bool`
    * *Implementation details:* Writes incoming generic JSON directly to a fast, append-only `.jsonl` queue.
* **`ConsolidationWorker` (Background Process)**
    * `start_watching(interval: float)`
    * *Implementation details:* Initialized with an `ensemble_path`. Uses `polars` to continuously drain the `.jsonl` queue, perform upserts/joins, and update the analytical columnar `.parquet` datasets.
* **`StorageQueryAPI` (Interface)**
    * `get_parameters(experiment_id: str, execution_id: str, iteration: int, columns: List[str] | None, realization: int | None) -> DataFrame`: API endpoint streams data as `application/vnd.apache.parquet`. Accepts slicing arguments to prevent frontend OOM issues.
    * `get_responses(experiment_id: str, execution_id: str, iteration: int, keys: List[str] | None, realization: int | None) -> DataFrame`: API endpoint streams data as `application/vnd.apache.parquet`. Accepts slicing arguments.
    * `get_manifest(experiment_id: str, execution_id: str, iteration: int) -> dict[str, float]`: Lightweight cache-busting endpoint returning the latest `.parquet` modification timestamps.
    * `flush(experiment_id: str, execution_id: str, iteration: int) -> bool`: Forces the Consolidator to drain the queue entirely before returning.
    * `get_update_metadata(experiment_id: str, execution_id: str, iteration: int) -> UpdateMetadata`: Retrieves the state, configuration, and metrics of the mathematical update that produced this iteration.
    * `write_update_metadata(experiment_id: str, execution_id: str, iteration: int, metadata: UpdateMetadata) -> None`: Writes the metadata of the mathematical update to the *posterior* iteration's storage directory (`iter-{iteration}/update_metadata.json`).

---

## 3. `gert.experiment_runner` (Execution & Orchestration)
This module acts as the conductor. It reads the config, sets up the environments, talks to the HPC scheduler, and manages state.

* **`ExperimentOrchestrator`**
    * `start_experiment(config: ExperimentConfig)`
    * `run_iteration(iteration: int, parameters: ParameterMatrix)`
    * `run_realization(realization_id: int, iteration: int)`
    * `cancel_execution()`: Hard blocking cancel that aborts all internal tasks and commands the `JobSubmitter` to purge the queues.
* **`JobSubmitter` (Interface wrapping `psij-python`)**
    * `submit(execution_steps: List[Step], queue_config: dict) -> str` (Returns backend job ID)
    * `cancel_all_jobs(experiment_id: str, execution_id: str)`: Hard blocking function to clear the cluster queue.
* **`RealizationWorkdirManager`**
    * `create_workdir(iteration: int, realization: int, parameters: dict) -> Path`
    * `cleanup_workdir(iteration: int, realization: int)` (Optional GC)
* **`HookManager`**
    * `execute_hook(hook_type: HookEnum, config: dict)`: Runs generic pre/post scripts.

---

## 4. `gert.update` (Mathematical Updates)
This module acts as a strict adapter layer. It takes flat DataFrames from `gert.storage`, passes them to external mathematical libraries, and returns the updated values.

* **`UpdateEngine` (Interface)**
    * `perform_update(prior_params: DataFrame, responses: DataFrame, observations: ObservationSet) -> ParameterMatrix`
    * *Implementation details:* This is where external libraries like `iterative_ensemble_smoother` are invoked. It handles flattening tensors to 1D vectors before math, and reshaping them back afterward.

---

## 5. `gert.parameters` (Prior Generation & Parameter Logic)
An isolated module dedicated purely to probability distributions and matrix generation, completely separated from execution.

* **`PriorGenerator` (Interface)**
    * `generate_matrix(distribution_config: dict, num_realizations: int) -> ParameterMatrix`
    * *Implementation details:* Wraps the `probabilit` library to convert user-defined probability distributions into the static initial matrix embedded in the `ExperimentConfig`.

---

## 6. `gert.server` (API Routers & Process Management)
This module exposes the internal modules as network services and manages their execution topologies.

### 6.1 API Design Principles
* **Real-Time Streaming:** The backend avoids HTTP polling where possible. Macro and granular state transitions are pushed to TUIs/GUIs via `WebSockets`.
* **Data Pagination/Slicing:** Analytical endpoints returning Parquet blobs (e.g. `/parameters`, `/responses`) MUST support query parameters (like `?columns=PERM&realization=5`). The backend uses lazy Polars evaluation to slice large out-of-core datasets *before* network transmission to protect UI memory.
* **Strict Iteration Separation (No Diffing):** API endpoints strictly scope data fetching to a specific iteration (e.g. `/ensembles/{iteration}/...`). The backend will *never* provide composite endpoints that pre-join "Prior vs Posterior" data. This ensures maximum decoupling: observation sets and active cell topologies might theoretically change between iterations, and the server remains a dumb storage router while the frontend retains full analytical control over how disparate iterations are overlaid.
* **Hard Cancellation:** A dedicated `POST /experiments/{id}/executions/{exec_id}/cancel` endpoint exists to trigger a cascade of aggressive interrupts down to the HPC scheduler.

### 6.2 Application Layer
* **`app.py` (FastAPI Applications)**
    * Maps HTTP endpoints (`POST /experiments`, `POST /experiments/.../cancel`, `GET /storage/...`) to internal controllers.
    * Maps WebSocket endpoints (`WS /experiments/.../events`) to the state tracker.
* **`ProcessManager`**
    * `boot_production()`: Spawns the Storage app, Experiment Runner app, and Parameters app in isolated OS processes.
    * `boot_dev()`: Spawns the apps in separate threads within a single process.
* **`SecurityContext`**
    * `generate_connection_file(base_path: Path) -> dict`
    * `verify_token(token: str) -> bool`
    * Handles signal trapping to guarantee deletion of `connection.json` upon exit/crash.

---

## 7. `gert.plugins.client` (External Interfaces)
The tools used by users or higher-level systems (like Everest) to interact with the server.

* **`ConnectionDiscovery`**: Reads the `chmod 600` `connection.json` file to configure network hosts, ports, and Bearer tokens.
* **`GERTClient`**: A Python HTTP client wrapper.
    * `client.submit_experiment(config)`
    * `client.stop_experiment(exp_id)`
    * `client.get_status(exp_id)`
* **`CLI`**: Uses `click` or `typer` to provide terminal commands (`gert start`, `gert stop`, `gert monitor`) that utilize the `GERTClient`.

---

## 8. Directory Structure & Full-Stack Model Sharing

The repository follows a strict directory structure that maps directly to the module boundaries described above. A key architectural benefit of this organization is how the core data models are shared across the entire stack.

Standard Folder Structure

```
gert/
├── pyproject.toml
├── docs/developers/              # Architecture, design rules, roadmap
├── src/
│   └── gert/                     # Base Python package
│       ├── client/               # External Python interfaces (GERTClient, CLI)
│       ├── experiment_runner/    # psij-python abstraction, RealizationWorkdirManager
│       ├── experiments/          # Core Immutable State
│       │   └── models.py         # Centralized Pydantic models
│       ├── parameters/           # Prior generation (probabilit integration)
│       ├── server/               # FastAPI application, routers, WebSockets
│       ├── storage/              # IngestionReceiver, Polars ConsolidationWorker
│       └── update/               # Math adapters (iterative_ensemble_smoother)
└── tests/
    ├── factories/                # Mock data and hypothesis factories
    ├── experiments/
    └── ...
```


Single Source of Truth for Models

The Pydantic models in src/gert/experiments/models.py serve as the absolute single source of truth for both the backend and frontend environments:

For Python Clients (Backend/CLI): Internal server modules and external Python clients (like Everest or the CLI in gert.plugins.client) simply import these models natively (from gert.experiments.models import ExperimentConfig).

For Web Frontends (UI): There is no need to manually rewrite these data structures in JavaScript/TypeScript. The FastAPI backend (gert.server) automatically reads the Pydantic models and generates a live OpenAPI (Swagger) JSON schema. Web frontends use tools like openapi-typescript-codegen to automatically generate perfectly typed frontend interfaces directly from this schema.
