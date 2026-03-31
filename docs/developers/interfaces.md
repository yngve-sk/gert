# GERT Interfaces and Module Organization

This document defines the core Python modules and abstract interfaces for the Generic Ensemble Reservoir Tool (GERT). Developers and AI assistants must strictly adhere to these boundaries to maintain the decoupled, generic architecture.

---

## 1. `gert.experiments` (Core Data Structures & Immutable State)
This module contains the strictly defined, domain-agnostic Pydantic models (or dataclasses) that represent the data at rest. These objects are purely data; they contain no execution or control logic, though they may contain pure data transformation methods (e.g., `to_df()`) to provide alternative representations.

* **`ExperimentConfig`**: The root immutable artifact. Contains the forward model steps, queue configurations, and a hard link to the initial `ParameterMatrix`.
* **`ParameterMatrix`**: A 2D deterministic dataset representing the exact values to inject into realizations.
* **`ObservationSet`**: A collection of expected responses mapped to physical/synthetic truth, fundamentally requiring `value` and `std_dev`.
* **`IngestionPayload`**: The generic JSON schema expected from forward models (e.g., `{"realization": int, "step": str, "data": dict}`).

---

## 2. `gert.storage` (Data Ingestion & Analytical Storage)
This module isolates all high-throughput disk I/O, message queuing, and Parquet consolidation. It does not know about jobs or clusters.

* **`IngestionReceiver` (Interface)**
    * `push_data(experiment_id: str, execution_id: str, payload: IngestionPayload) -> bool`
    * *Implementation details:* Writes incoming generic JSON directly to a fast, append-only `.jsonl` queue.
* **`ConsolidationWorker` (Background Process)**
    * `start_watching(queue_path: Path, parquet_path: Path)`
    * *Implementation details:* Uses `polars` to continuously drain the `.jsonl` queue, perform upserts/joins, and update the analytical columnar `.parquet` datasets.
* **`StorageQueryAPI` (Interface)**
    * `get_parameters(experiment_id: str, execution_id: str, iteration: int) -> DataFrame`
    * `get_responses(experiment_id: str, execution_id: str, iteration: int, keys: List[str] | None) -> DataFrame`
    * `flush(experiment_id: str, execution_id: str, iteration: int) -> bool`: Forces the Consolidator to drain the queue entirely before returning.

---

## 3. `gert.experiment_runner` (Execution & Orchestration)
This module acts as the conductor. It reads the config, sets up the environments, talks to the HPC scheduler, and manages state.

* **`ExperimentOrchestrator`**
    * `start_experiment(config: ExperimentConfig)`
    * `run_iteration(iteration: int, parameters: ParameterMatrix)`
    * `run_realization(realization_id: int, iteration: int)`
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

* **`app.py` (FastAPI Applications)**
    * Maps HTTP endpoints (`POST /experiments`, `GET /storage/...`) to internal controllers.
    * Maps WebSocket endpoints (`WS /events`) to the state tracker.
* **`ProcessManager`**
    * `boot_production()`: Spawns the Storage app, Experiment Runner app, and Parameters app in isolated OS processes.
    * `boot_dev()`: Spawns the apps in separate threads within a single process.
* **`SecurityContext`**
    * `generate_connection_file(base_path: Path) -> dict`
    * `verify_token(token: str) -> bool`
    * Handles signal trapping to guarantee deletion of `connection.json` upon exit/crash.

---

## 7. `gert.client` (External Interfaces)
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

For Python Clients (Backend/CLI): Internal server modules and external Python clients (like Everest or the CLI in gert.client) simply import these models natively (from gert.experiments.models import ExperimentConfig).

For Web Frontends (UI): There is no need to manually rewrite these data structures in JavaScript/TypeScript. The FastAPI backend (gert.server) automatically reads the Pydantic models and generates a live OpenAPI (Swagger) JSON schema. Web frontends use tools like openapi-typescript-codegen to automatically generate perfectly typed frontend interfaces directly from this schema.
