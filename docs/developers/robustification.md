# GERT Robustness & Distributed Failure Handling

GERT operates as a distributed system: a central orchestrator dispatches asynchronous jobs to external compute resources (local processes or HPC clusters) which then independently report data back to the server via an HTTP API.

This architecture is powerful and scalable but inherently susceptible to race conditions, network failures, node crashes, and state synchronization issues. To ensure GERT remains stable, observable, and crash-proof, all development must adhere to the robustness principles outlined in this document.

These principles guide our immediate priorities for system hardening and should be consulted when adding new features or debugging complex asynchronous failures.

---

## 1. Network & Ingestion Failures (Forward Models -> Server)

**The Problem:**
Forward models (user-provided executables) are transient and run in isolated environments. If they attempt to send their simulated responses back to the GERT server and the network blips, the server is restarting, or the request times out, the forward model often exits. The orchestrator may see the job complete (exit code 0 via the job scheduler) but the expected data is missing, leading to downstream mathematical crashes.

**Design Principles:**
*   **Robust Client SDK:** Forward models should not rely on raw HTTP requests (`httpx`, `requests`, `curl`). GERT must provide a standardized, lightweight client utility (e.g., `gert.plugins.client`) that handles authentication, routing, and data serialization.
*   **Mandatory Retries (Exponential Backoff):** The client SDK must implement robust retry logic. If the server is unreachable or returns a 50x error, the client must retry with exponential backoff for a generous configurable period before giving up.
*   **Application-Level Completion Signals:** The orchestrator must not rely on the OS-level exit code (via PSI/J) to determine if a job succeeded. The SDK must explicitly send a `POST /complete` signal *after* all data is successfully ingested. If the job catches an error, it should send a `POST /fail` signal with the traceback.
*   **Fail-Fast Job Exits:** If a forward model ultimately cannot ingest its data after exhausting all retries, it **must** exit with a non-zero error code (e.g., `sys.exit(1)`).

---

## 2. Job Execution & Orchestration Synchronization

**The Problem:**
The orchestrator relies on counting job completion events to advance to the math update phase. If jobs fail, finish too fast (before state is initialized), or take days in an HPC queue, the orchestrator's state machine can hang, crash, or proceed prematurely.

**Design Principles:**
*   **Hybrid State Tracking (HTTP + Scheduler):** The orchestrator's state machine should be primarily driven by the HTTP `/complete` and `/fail` signals sent by the SDK. PSI/J acts strictly as a *fallback supervisor* (a dead man's switch). If PSI/J reports a job failed or was killed (e.g., OOM kill, hardware failure) before the HTTP signal arrives, the orchestrator marks it as failed. If PSI/J reports success but no HTTP `/complete` was received, it is treated as a silent failure.
*   **Deterministic State Initialization:** The orchestrator must completely initialize all synchronization primitives (e.g., `asyncio.Event`, tracking dictionaries, expected counts) for an iteration *before* dispatching the first job.
*   **Iteration Short-Circuiting (Fail-Fast):** If a critical threshold of realizations fails (or even a single one, depending on configuration), the orchestrator should gracefully halt the iteration, cancel pending jobs, and mark the overall execution state as `FAILED`.
*   **Scheduler-Driven Timeouts:** The orchestrator should not use hardcoded local timeouts (e.g., 120 seconds) for waiting on jobs. Timeouts must be explicitly configurable via `ExperimentConfig.queue_config.walltime`, deferring to the HPC scheduler's limits where possible.

---

## 3. Server State & Crash Recovery

**The Problem:**
Currently, execution state (experiment configurations, running orchestrator tasks, job statuses) resides entirely in the FastAPI server's RAM. If the server process restarts or crashes during a long-running HPC experiment, all memory is lost. Running cluster jobs will eventually attempt to ingest data to a server that no longer recognizes their `experiment_id`, resulting in 404 errors and lost work.

**Design Principles:**
*   **Single Source of Truth (Event Sourcing):** GERT does not store a mutable `execution_state.json`. Instead, all state is recorded as discrete progress events in an append-only `status_events.jsonl` file.
*   **ExecutionState is Computed, Not Stored:** The `ExecutionState` object is a *computed view* dynamically reconstructed from the event log on demand (or at startup). This completely eliminates race conditions where memory and storage disagree.
*   **Stateless API Design:** The ingestion API should validate against the persistent storage layer, not just an in-memory dictionary. If a request arrives for an active experiment, the server should be able to accept it even if it just rebooted by rebuilding the state from the log.
*   **Recovery/Resume Capability (Future):** The server startup sequence should eventually include a recovery phase: scanning the storage directory for incomplete executions, rebuilding their state from `status_events.jsonl`, querying the job scheduler (PSI/J) for the status of known external jobs, and seamlessly resuming the orchestrator loops.

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

---

## 6. Execution Lifecycle Control (Pause, Resume, and Force Kill)

**The Problem:**
Users running large-scale HPC experiments might need to temporarily halt execution to free up compute resources, inspect intermediate mathematical updates, or prevent runaway costs. Additionally, if the server crashes (Section 3), it needs a structured way to "resume" an execution that was unceremoniously halted. Currently, stopping an experiment requires killing the server, and there is no way to resume.

**Design Principles:**
*   **Graceful Pause (`POST /experiments/{id}/executions/{id}/pause`):** By default, pausing an experiment should not kill running work. The orchestrator transitions its state to `PAUSING`. It stops submitting *new* forward models but continues to listen for `/complete` and `/fail` signals for currently active jobs. Once all active jobs resolve, the execution transitions to `PAUSED`, and the orchestrator loop exits cleanly.
*   **Forceful Pause (`POST /experiments/{id}/executions/{id}/pause?force=true`):** If a user needs an immediate halt, the `force=true` query parameter instructs the orchestrator to transition immediately to `PAUSED`. The orchestrator must actively iterate through its list of active job IDs and invoke the job scheduler's cancellation mechanism (e.g., PSI/J cancel) before exiting the loop.
*   **Resume (`POST /experiments/{id}/executions/{id}/resume`):** When resuming an execution (either from a `PAUSED` state or recovering from a crashed server), the orchestrator must dynamically evaluate its current iteration. It reads `config.json` and evaluates the `status_events.jsonl` log. By comparing the expected realizations against the successfully ingested step data and known failed jobs, it identifies which realizations are missing or incomplete. It then submits *only* the missing realizations (restarting failed ones from scratch initially, or from partial steps in the future), transitions back to `RUNNING`, and re-enters the standard macro loop.
