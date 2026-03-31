# GERT Robustness & Distributed Failure Handling

GERT operates as a distributed system: a central orchestrator dispatches asynchronous jobs to external compute resources (local processes or HPC clusters) which then independently report data back to the server via an HTTP API.

This architecture is powerful and scalable but inherently susceptible to race conditions, network failures, node crashes, and state synchronization issues. To ensure GERT remains stable, observable, and crash-proof, all development must adhere to the robustness principles outlined in this document.

These principles guide our immediate priorities for system hardening and should be consulted when adding new features or debugging complex asynchronous failures.

---

## 1. Network & Ingestion Failures (Forward Models -> Server)

**The Problem:**
Forward models (user-provided executables) are transient and run in isolated environments. If they attempt to send their simulated responses back to the GERT server and the network blips, the server is restarting, or the request times out, the forward model often exits. The orchestrator may see the job complete (exit code 0) but the expected data is missing, leading to downstream mathematical crashes.

**Design Principles:**
*   **Robust Client SDK:** Forward models should not rely on raw HTTP requests (`httpx`, `requests`, `curl`). GERT must provide a standardized, lightweight client utility (e.g., `gert.client`) that handles authentication, routing, and data serialization.
*   **Mandatory Retries (Exponential Backoff):** The client SDK must implement robust retry logic. If the server is unreachable or returns a 50x error, the client must retry with exponential backoff (e.g., using `tenacity` or `urllib3` retry adapters) for a generous configurable period before giving up.
*   **Fail-Fast Job Exits:** If a forward model ultimately cannot ingest its data after exhausting all retries, it **must** exit with a non-zero error code (e.g., `sys.exit(1)`). This signals to the job scheduler (PSI/J) and the orchestrator that the realization *failed*, preventing the system from falsely assuming success and proceeding with missing data.

---

## 2. Job Execution & Orchestration Synchronization

**The Problem:**
The orchestrator relies on counting job completion events to advance to the math update phase. If jobs fail, finish too fast (before state is initialized), or take days in an HPC queue, the orchestrator's state machine can hang, crash, or proceed prematurely.

**Design Principles:**
*   **Deterministic State Initialization:** The orchestrator must completely initialize all synchronization primitives (e.g., `asyncio.Event`, tracking dictionaries, expected counts) for an iteration *before* dispatching the first job.
*   **Explicit Success vs. Failure Tracking:** The orchestrator must distinguish between `successful_realizations` and `failed_realizations`. A job that exits with an error must not be counted towards the "ready for math update" threshold.
*   **Iteration Short-Circuiting (Fail-Fast):** If a critical threshold of realizations fails (or even a single one, depending on configuration), the orchestrator should gracefully halt the iteration, cancel pending jobs, and mark the overall execution state as `FAILED`. It should log a clear summary of which realizations failed rather than proceeding to a mathematical crash.
*   **Scheduler-Driven Timeouts:** The orchestrator should not use hardcoded local timeouts (e.g., 120 seconds) for waiting on jobs. In HPC environments, jobs may queue for days. Timeouts must be either completely disabled (relying on the cluster's walltime limits) or explicitly configurable via `ExperimentConfig.queue_config.walltime`.

---

## 3. Server State & Crash Recovery

**The Problem:**
Currently, execution state (experiment configurations, running orchestrator tasks, job statuses) resides entirely in the FastAPI server's RAM. If the server process restarts or crashes during a long-running HPC experiment, all memory is lost. Running cluster jobs will eventually attempt to ingest data to a server that no longer recognizes their `experiment_id`, resulting in 404 errors and lost work.

**Design Principles:**
*   **Persistent State Representation:** The orchestrator must serialize its core state (status, current iteration, active job IDs) to a persistent backing store (e.g., `execution_state.json` within the `permanent_storage` directory) alongside the data.
*   **Stateless API Design:** The ingestion API should validate against the persistent storage layer, not just an in-memory dictionary. If a request arrives for an active experiment, the server should be able to accept it even if it just rebooted.
*   **Recovery/Resume Capability (Future):** The server startup sequence should eventually include a recovery phase: scanning the storage directory for incomplete executions, querying the job scheduler (PSI/J) for the status of known external jobs, and seamlessly resuming the orchestrator loops.

---

## 4. Consolidation Worker Robustness

**The Problem:**
The `ConsolidationWorker` asynchronously drains the highly concurrent `.jsonl` ingestion queues into strongly typed Parquet tables. If the worker encounters malformed data, schema mismatches, or file locking issues, it must not crash silently or drop data, as this starves the mathematical plugins.

**Design Principles:**
*   **Dead Letter Queue (DLQ):** If a record cannot be parsed or lacks required schema keys, it must be appended to an `errors.jsonl` or `dlq.jsonl` file alongside the reason for failure. It should not simply be skipped with a log message. This provides an audit trail for users to fix their forward models.
*   **Supervisor Pattern:** Background tasks like consolidation should not be "fire and forget". The orchestrator should monitor the health of its dedicated consolidation workers. If a worker task raises an unhandled exception and dies permanently, the orchestrator must catch this and fail the iteration gracefully, explaining that data consolidation halted.
*   **Atomic Operations:** File operations (renaming queues, upserting Parquet files) must be as atomic as possible to prevent corruption if the server crashes mid-write.

---

## 5. Clear, User-Facing Error Context

**The Problem:**
When a failure occurs deep within a mathematical plugin or during background job submission, the orchestrator catches it and outputs a raw Python traceback. This is useful for developers but hostile to end-users trying to figure out what went wrong with their experiment configuration.

**Design Principles:**
*   **Standardized Exception Hierarchy:** Implement specific error types (e.g., `GERTIngestionError`, `GERTMathUpdateError`, `GERTConfigurationError`, `GERTJobSubmissionError`).
*   **Contextual Error Summaries:** When the orchestrator catches an exception and transitions an execution to `FAILED`, it must format a structured, user-friendly summary.
    *   *Instead of:* `ValueError: shapes (20,100) and (100,50) not aligned`
    *   *Provide:*
        *   **Phase:** Math Update (Iteration 2)
        *   **Plugin:** `enif_update`
        *   **Reason:** Matrix dimension mismatch between updated parameters and observations.
        *   **Traceback:** (Attached below for debugging)
*   **CLI Surfacing:** The GERT CLI must poll the execution state and instantly surface these structured errors to the user's terminal, preventing the appearance of a "hung" process when the background has actually failed.
