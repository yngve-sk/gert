# GERT Development Roadmap

This document outlines the strategic, phased approach for building GERT (Generic Ensemble Reservoir Tool). Development is structured incrementally into standalone Pull Requests (PRs). Every micro-step MUST leave the codebase in a fully working, testable state. No intermediate broken builds are allowed.

---

## Phase 1: Foundation & The Immutable Core
**Goal:** Establish the project skeleton, enforce the strict data models, and set up the local development server.

* **PR 1.1: Project Tooling & Setup**
    * Initialize `pyproject.toml` with `ruff` (`select = ["ALL"]`), `mypy` (strict), `pytest`, and `hypothesis`.
    * Setup `.pre-commit-config.yaml`.
    * Create the base folder structure (`src/gert/`, `tests/factories/`).
* **PR 1.2: Core Immutable Models (`gert.experiments`)**
    * Implement Pydantic models: `ParameterMatrix`, `IngestionPayload`, `ObservationSet` (requiring `value` and `std_dev`), and the root `ExperimentConfig`.
    * Write `hypothesis` property tests asserting strict validation boundaries and "Fail Fast" behavior.
* **PR 1.3: Centralized Test Factories**
    * Implement `tests/factories/experiment_factory.py` to generate valid dummy configs and matrices.
* **PR 1.4: Base API Server (`gert.server`)**
    * Setup FastAPI application with `POST /experiments` and `GET /experiments/{id}/config`.
    * Mock the backend storage for now. Write fast API route tests.

---

## Phase 2: The Data Ingestion Engine
**Goal:** Build the high-throughput, decoupled storage backend.

* **PR 2.1: The Ingestion Queue**
    * Implement `IngestionReceiver` to accept `IngestionPayload` and append to a fast `.jsonl` queue.
    * Write unit tests verifying file-system append behavior.
* **PR 2.2: The Polars Consolidation Worker**
    * Implement the background `ConsolidationWorker` using `polars` to drain `.jsonl` and upsert into columnar `.parquet` files.
    * Write unit tests verifying data aggregation and schema consistency.
* **PR 2.3: Storage Query API**
    * Implement `StorageQueryAPI` and expose via FastAPI (`GET /storage/{exp_id}/responses`).
* **PR 2.4: Storage Integration Test**
    * Write a minimal integration test that blasts 100 concurrent JSON payloads to the API and verifies the Parquet file is correctly consolidated.

---

## Phase 3: Execution & Orchestration
**Goal:** Connect GERT to compute resources and run a "blind" forward model.

* **PR 3.1: Runpath Management**
    * Implement `RunpathManager` to create temporary scratch directories and inject exact parameters from the `ParameterMatrix`.
    * Write unit tests verifying file creation and optional GC cleanup.
* **PR 3.2: Job Submitter (`psij-python`)**
    * Implement `JobSubmitter` using `psij-python` for local/cluster abstraction.
    * Write mocked unit tests verifying `psij` adapter calls.
* **PR 3.3: Experiment Orchestrator**
    * Implement `ExperimentOrchestrator` to coordinate the runpath and job submission based on the `ExperimentConfig`.
    * Wire up the `/start` endpoint.
* **PR 3.4: End-to-End Local Execution**
    * Write a minimal integration test: Submit an experiment with a dummy Python forward model that reads the runpath and pushes data to the Ingestion API.

---

## Phase 4: The Assimilation Loop
**Goal:** Introduce mathematical updates and close the iterative loop.

* **PR 4.1: Storage-to-Math Adapter**
    * Implement logic to flush the `ConsolidationWorker`, read the Parquet files, and flatten tensors into 2D matrices.
    * Write `hypothesis` tests ensuring shape preservation during flattening/reshaping.
* **PR 4.2: The Update Engine (`gert.update`)**
    * Implement `UpdateEngine` adapter to invoke external math libraries (e.g., `iterative_ensemble_smoother`).
    * Write unit tests mocking the math library response.
* **PR 4.3: Iteration Loop Orchestration**
    * Update `ExperimentOrchestrator` to catch iteration completion, trigger the update, save the new `ParameterMatrix` to storage, and launch the next iteration.
    * Write an integration test for a full multi-iteration run using a dummy math update.

---

## Phase 5: Everest Integration
**Goal:** Mount the optimization layer on top of the generic execution engine.

* **PR 5.1: Everest Translation Layer**
    * Refactor Everest to convert its control variables into a standard GERT `ParameterMatrix`.
* **PR 5.2: Everest Client API Driver**
    * Configure Everest to `POST` matrices to GERT, poll for completion, and extract generic responses to calculate gradients.

---

## Phase 6: Observability & Frontend Readiness
**Goal:** Harden the API, handle failures gracefully, and make it ready for a GUI.

* **PR 6.1: Event Streaming (WebSockets)**
    * Implement `WS /experiments/{id}/events` to broadcast asynchronous state changes.
* **PR 6.2: Blocking Cancellation**
    * Implement `POST /experiments/{id}/stop` ensuring active `psij-python` job termination before returning.
* **PR 6.3: Ephemeral Security & Lifecycle**
    * Implement `SecurityContext` to generate `connection.json` with dynamic ports and strict POSIX permissions.
    * Implement robust signal handling (`SIGTERM`, `SIGINT`) to guarantee file deletion on shutdown.