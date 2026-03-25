# GERT High-Level Architecture

## System Topology
GERT is designed as an API-first, domain-agnostic orchestration engine. Its architecture is composed of three primary, decoupled services:

1.  **Orchestration API (`gert.server`):** A `FastAPI` application that serves as the central control plane. It receives experiment configurations, manages execution state, and delegates tasks.
2.  **Execution Engine (`gert.execution`):** The component responsible for managing the job lifecycle. It translates abstract execution steps from the configuration into concrete jobs via `psij-python` and submits them to the target scheduler (e.g., local process, HPC cluster).
3.  **Storage Service (`gert.storage`):** A service that handles the ingestion and consolidation of sparse data pushed from forward models. It collects `.jsonl` fragments and incrementally builds columnar `.parquet` files for efficient analysis.

---

## Experiment I/O and Directory Structure
To ensure GERT experiments are self-contained, reproducible, and portable, all file system interactions are strictly defined within the `ExperimentConfig`. Relying on the current working directory or other implicit paths is strictly forbidden.

Each execution of an experiment must be isolated to prevent data corruption between runs. Therefore, GERT uses a nested directory structure based on the `experiment_id` (the immutable configuration) and then the `execution_id` (a specific run of that configuration).

GERT defines two primary, configurable paths for managing experiment I/O:

*   **`realization_workdirs_base` (Base for Realization Workdirs):**
    *   **Purpose:** The top-level directory under which GERT creates temporary, isolated "realization workdirs" for executing each forward model.
    *   **Structure:** Workdirs for a specific run are located at:
        `<realization_workdirs_base>/<experiment_id>/<ensemble_id>/`
    *   **Behavior:** This directory contains sandboxed environments for each model run and is considered ephemeral. GERT may clean up its contents after an execution completes successfully. Defaults to `./workdirs`.

*   **`storage_base` (Base for Persistent Storage):**
    *   **Purpose:** The top-level directory for storing all persistent artifacts generated during an experiment, such as consolidated responses, logs, and other critical outputs.
    *   **Structure:** Persistent artifacts for a specific run are located at:
        `<storage_base>/<experiment_id>/<ensemble_id>/`
    *   **Behavior:** This directory contains the final, valuable results of the experiment and must be preserved. Data within this path is the source of truth for resuming a failed execution. Defaults to `./permanent_storage`.

This explicit and nested approach ensures that the I/O for every execution is entirely predictable and isolated, deriving its configuration from a single, immutable source file.


# Architecture of GERT (Generic Ensemble Reservoir Tool)

## 1. Core Experiment & Configuration (The Immutable Artifact)
* **Experiment Objects:** GERT experiments are specified as objects corresponding to different runmodel configs, each encapsulating an entire experiment.
* **Separation of Sampling & Execution:** The core execution engine does not sample probability distributions. Its fundamental baseline input is a deterministic **Parameter Set** (a matrix of exact values for each realization).
* **The Config as an Immutable Artifact:** Once an experiment is initialized, its runmodel config becomes an absolute, immutable source of truth for reproducibility, permanently embedding the exact Parameter Set used.
* **Parameter Input Modes:**
    1.  **Pre-sampled Input:** The user provides an explicit dataset (e.g., a JSON matrix) via the API.
    2.  **Distribution Config (Convenience):** The user provides probability distributions. GERT invokes the `probabilit` library to draw samples and generate the static Parameter Set matrix before execution begins.

## 2. Generic Data Model (Domain Agnosticism)
* **Parameters & Responses:** GERT possesses no domain-specific knowledge. Parameters are treated as generic 1D/2D/3D tensors or scalar values. Responses are datasets produced by a step in the forward model (e.g., a specific file expected to exist, or a generic `.json` dictionary).
* **Observations:** Observations are provided by the user as references to responses. Crucially for data assimilation, they fundamentally require standard deviations/errors (e.g., `{"key": "FOPR", "time": "2010-0-0", "value": 2, "std_dev": 0.5}`).

## 3. System Components
GERT operates as a distributed system composed of specific, decoupled services:
* **Sampling Server:** A dedicated service utilizing `probabilit` to handle parameter distribution definitions and matrix generation.
* **Storage Server:** The persistent data host managing the Data Ingestion API, message queues, analytical datasets, and live querying.
* **Experiment Runner Server:** The core orchestration engine controlling the experiment lifecycle, invoking mathematical updates, context-validating the runmodel config (checking expected Python plugins/environment), and managing job submissions.
* **Execution Environment (Compute Layer):** The external infrastructure (HPC schedulers like Slurm/LSF or local workers) running the actual simulations.
* **Client Interfaces:** The CLI, Web GUI, or external layers (like Everest) that drive the APIs.

## 4. The Forward Model & Execution
* **Sequential Steps:** The forward model consists of several sequential steps specified in the runmodel config.
* **Job Submission:** Forward models are executed using `psij-python`. The "queue config" maps to inputs for `psij-python`, abstracting away cluster-specific schedulers (LSF, Slurm, OpenPBS) or local shells.
* **Realization Workdir Lifecycle & Optional GC:** Executions utilize a temporary directory (e.g., `realization-n/iteration-n` on scratch disk) injected with exact parameter values. Because vital data is pushed to storage, GERT supports an **optional garbage collection** policy to clean up temporary workdirs after a successful realization.

## 5. Data Ingestion & Storage (Incremental & Persistent)
* **Long-Running Service:** Permanent "dark storage" relies on the Storage Server, booted at experiment start and kept active throughout the lifecycle.
* **Sparse, Real-Time Ingestion (Push, Not Poll):** Forward models emit "sparse" data via HTTP/gRPC as it is generated (or via post-run parsing scripts). To ensure high throughput without locking, the ingestion service writes incoming payloads to a fast, append-only `.jsonl` message queue.
* **Incremental Consolidation (Polars):** A background process continuously reads the `.jsonl` queue and uses `polars` to parse, aggregate, and perform joins/upserts to consolidate the sparse updates into permanent storage.
* **Storage Format (Parquet):** Permanent storage consists of columnar `.parquet` files, organized per response schema (**one row per realization**, **one column per response key**).
* **Live Inspectability & The Flush:** Because consolidation happens incrementally, users can query partial data during runtime. At the end of an iteration, a callback guarantees the queue is drained and Parquet files are fully up-to-date (flushed) before the mathematical update.

## 6. Failure Handling & State Management
* **Failures & Manual Restarts:** HPC Schedulers will not automatically restart failed jobs. GERT does not attempt complex mid-step resumption. Users manually trigger a restart of failed realizations via the API. The server looks up the exact parameter values in the immutable config and reboots the forward model from scratch.

## 7. Algorithms & Math
* External Math Libraries: Update algorithms rely strictly on external mathematical libraries (e.g., iterative_ensemble_smoother for ES/IES/ES-MDA, and graphite maps for EnIF).
* The Update Step: The algorithm consumes the fully consolidated Parquet datasets (responses and current parameters) from the storage layer and calculates a new Parameter Set for the next iteration.
* State vs. Configuration: This new Parameter Set is not appended to the experiment config. The experiment config remains an immutable record of only the first (prior) parameter set. Instead, the updated Parameter Set is pushed to the Storage Server as part of the new iteration's dataset, where the Experiment Runner will fetch it to execute the next round of forward models.

## 8. Everest Integration (Ensemble-Based Optimization)
* Everest is treated strictly as a generic, domain-agnostic **ensemble-based optimization layer** sitting on top of GERT.
* Everest handles optimization concepts (objective functions, constraints). It generates a deterministic set of control variables, formats them as a standard GERT Parameter Set matrix, and `POST`s them to the GERT API for blind execution.

## 9. Experiment Hooks
* Formerly known as "Workflows". GERT supports generic scripts or routines that run outside the bounds of individual realization forward models (e.g., downloading shared grid data pre-experiment, or running a reporting script post-experiment).

## 10. API, Observability, & Control
* **Core API Endpoints:**
    * `POST /experiments`: Creates a new experiment from a runmodel config.
    * `GET /experiments/{exp_id}/config`: Retrieves the complete, immutable configuration.
    * `GET /experiments/{exp_id}/status`: Provides a summarized inspection of progress.
    * `WS /experiments/{exp_id}/events`: A WebSocket endpoint for real-time granular updates on realizations and ingestion states.
    * `/storage/*`: Retrieves analytical data from dark storage.
* **Blocking Cancellation:** `POST /experiments/{exp_id}/stop` strictly blocks. It actively passes kill commands down to `psij-python` and will not return an `OK` until verifying all associated cluster jobs are successfully shut down.

## 11. Execution Model, Deployment & Security
* **Production (Multi-Process):** By default, executing GERT spawns and manages separate, isolated OS processes for the Storage, Runner, and Sampling servers to ensure fault isolation.
* **Local Development (Single-Process):** A `--dev` flag boots all services on separate threads within a single Python process for frictionless debugging.
* **File-System Security:** GERT bypasses complex IAM/OIDC by generating a secure, randomized access token and binding dynamic ports at startup. This payload is written to a local `connection.json` file locked down with strict POSIX permissions (`chmod 600`).
* **Ephemeral Lifecycle:** The `connection.json` file is strictly ephemeral. GERT utilizes robust signal handling (catching `SIGTERM`, `SIGINT`, and crashes) to **guarantee the deletion of this file upon shutdown or fatal error**. Clients must pass this token via `Authorization: Bearer <token>`.

## 12. Testing & Data Mocking Strategy
* **Strict Separation of Concerns:** Test orchestration and mock data generation are strictly kept out of the production application code.

## 13. Misc
* Iterations and realization nrs may never be negative, and these cases should not be tested, but rather guarded against.
* experiments / ensembles are identified by name/counter suffixed by uuids (e.g., `my_exp-550e8400...` and `run_0-550e8400...`)
* Names of things, experiments, ensembles, parameters, observations, responses should be sensible and not contain obscure or bizzarre characters, and it is OK to enforce this in GERT.
