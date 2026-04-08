# GERT Monitoring Views Specification

This document defines the required information architecture and data points for GERT's monitoring interfaces. It serves as the specification for the current Textual-based CLI monitor (`src/gert/monitor.py`) and acts as a blueprint for any future monitoring tools (e.g., a Web GUI or dashboard).

The monitoring interface is organized hierarchically. As a user navigates deeper into the execution tree, the views transition from high-level aggregations to granular execution details.

## 1. Execution Browser View (Cross-Execution)
This is the highest-level view in the TUI, acting as a directory of all runs for a specific experiment configuration.

*   **Content:** A list or table of all discovered executions for the loaded experiment configuration, sorted from newest to oldest.
*   **Metrics:** Displays the Execution ID, Start/Last Modified Time, and overall Status (fetched via the API).
*   **Interaction:** The user navigates the list, selects an execution, and presses `Enter` to drill down into the standard execution dashboard (described below).
*   **Navigation:** Users currently viewing a specific execution's dashboard can always navigate "up" (e.g., by pressing `Escape` or `b`) to return to this Execution Browser, allowing seamless switching between historical and active runs.

## 2. Global / Application View (Per-Execution)
This view provides persistent, high-level context for a *single* execution, regardless of the specific node selected in the navigation tree.

### 1.1 Header & Status Summary
*   **Experiment Identifier**: The `experiment_id` and `execution_id` currently being monitored.
*   **Global State**: The overall status of the execution (e.g., `PENDING`, `RUNNING`, `PAUSED`, `COMPLETED`, `FAILED`).
*   **State Aggregation**: A live tally of realization statuses across the active iteration (e.g., `RUNNING: 5 | COMPLETED: 15 | FAILED: 0`).

### 1.2 Iteration Progress Tracking
A tabular or list view summarizing the progress of *all* iterations in the experiment.
*   **Columns/Metrics per Iteration Row**:
    *   **Iteration Name/Number**: (e.g., `Iteration 0`, `Iteration 1`).
    *   **Progress Bar**: Visual indicator of `completed_realizations` / `total_realizations`.
    *   **⚙️ Forward Model Steps**: `{completed_steps}/{total_planned_steps}`.
    *   **📤 Responses**: Total number of simulated responses emitted in this iteration.
    *   **Δ Misfit**: The sum of `absolute_misfit` for each observation (if `ObservationSummary` is available).

---

## 3. Detail Views (Node-Specific)
When a specific node in the hierarchical execution tree is selected, the detail pane updates to show context-specific information.

### 3.1 Experiment (Root) Summary
Displayed when the root node of the experiment is selected. It acts as the primary dashboard for the run.

*Note: To build this dashboard, client applications should fetch the full `/experiments/{experiment_id}/config` endpoint. In Python contexts, the `ExperimentConfig` Pydantic model provides pure function getters (e.g., `.num_iterations`, `.num_observations`, `.num_parameters`) to efficiently compute these structural bounds dynamically without requiring a dedicated metadata endpoint.*

**Identification & Scope**
*   **Name**: `ExperimentConfig.name`
*   **Execution ID**: `ExecutionState.execution_id`
*   **👥 Ensemble Size**: Number of realizations.
*   **🔄 Total Iterations**: Number of planned updates + 1 (Prior).
*   **⚙️ FM Steps per Realization**: Number of forward model steps defined in the config.
*   **🎯 Total Observations**: Number of observation points configured for assimilation.

**Timeline & Status**
*   **Current State**: `ExecutionState.status` (e.g., `RUNNING`, `COMPLETED`, `FAILED`).
*   **Progress**: Current active iteration / Total iterations.
*   **📅 Started**: ISO timestamp of when the execution began (extracted from the earliest step start time or an execution-level timestamp).
*   **🕒 Elapsed Time**: Total time since the experiment began (calculated from start time to current time, or end time if completed).

### 3.2 Iteration Summary
Displayed when an `Iteration N` node is selected.

**Iteration Metrics**
*   **Header**: `◆ Iteration {N} Summary`
*   **Status**: A high-level status indicator based on realization completion (e.g., `Status: ✓ COMPLETED` or `Status: ◐ RUNNING`).
*   **🕒 Time Elapsed**: Duration from the first step's start time to the last step's end time within this specific iteration.

**Execution Progress**
*   **⚙️ Forward Model Steps**: `{completed_steps} / {total_planned_steps}` for this iteration.

**Data & Assimilation Statistics**
*   **📤 Responses Received**: Total number of simulated response records collected across all realizations in this iteration.
*   **🎯 Sum Abs Misfit**: The sum of `absolute_misfit` across all observations from the `ObservationSummary` (shows the total error magnitude of the ensemble, normalized by standard deviation).
*   **📉 Average Absolute Residual**: The raw physical unit error (`average_absolute_residual`).

### 3.3 Mathematical Update Summary
Displayed when an `🧮✨ Update (Iter N-1 → N)` node is selected.

**Algorithm & Status**
*   **Header**: `🧮✨ Mathematical Update`
*   **Algorithm**: The name of the plugin/algorithm used (e.g., `Ensemble Smoother`).
*   **Status**: `UpdateMetadata.status` (e.g., `RUNNING`, `COMPLETED`, `FAILED`).
*   **Duration**: Start time, end time, and total elapsed seconds (`duration_seconds`).
*   **Error**: Full error message/traceback if the update failed.

**Configuration & Metrics**
*   **Configuration**: JSON/Dictionary representation of the specific hyperparameters passed to the algorithm (`UpdateMetadata.configuration`).
*   **Metrics**: Custom metrics emitted by the algorithm (e.g., `prior_variance`, `posterior_variance`, `misfit_bias`).

### 3.4 Realization Summary
Displayed when a specific `Realization R (It N)` node is selected.

**Status & Identification**
*   **Header**: `● Realization {R} (Iteration {N})`
*   **Status**: Current state of this realization (`PENDING`, `RUNNING`, `COMPLETED`, `FAILED`).
*   **⚙️ Step Progress**: Number of completed steps / total steps for this realization.
*   **Current Step**: The name of the currently running step (if status is `RUNNING`).

**Data Output**
*   **📤 Responses Emitted**: Total count of responses generated by this realization.
*   **Last Response Details**:
    *   Key/Value pairs of the most recently emitted response (e.g., `response: FOPR`, `time: 10`, `Value: 123.45`).

### 3.5 Step Detail View
Displayed when a specific forward model step node is selected under a realization.

**Execution Context**
*   **Header**: `⚙️ {step_name} (Realization {R}, Iteration {N})`
*   **Status**: Step execution status.
*   **🕒 Timeline**: Start time and End time (or "Running...").

**Logs**
*   **STDOUT**: The standard output stream from the step execution.
*   **STDERR**: The standard error stream from the step execution (critical for debugging failures).
*(Note: In the CLI, logs might be split into sub-nodes to prevent massive text blocks from freezing the UI, but conceptually they belong to the Step view).*

---

## 4. UI/UX Conventions (CLI vs. Web)

While the data requirements are identical, the presentation formats differ based on the medium:

*   **Icons**: Standardized icons should be used to differentiate entity types quickly.
    *   🌍 for Forward Model Steps.
    *   🔥 for Responses / Output data.
    *   💧 for Parameters / Input data.
    *   🎯 or `Δ` for Observations / Misfits.
    *   🧱 for Realizations.
    *   🧱..🧱 for Iterations.
    *   🧮✨ for Mathematical Updates.
*   **Live Updates**: Views must handle asynchronous updates gracefully. If an iteration is currently running, misfit statistics won't exist yet; the UI should display "N/A", "Calculating...", or hide the field rather than throwing an error.
*   **Navigation**: The CLI uses a Tree widget on the left. A Web GUI might use a similar sidebar, breadcrumbs, or drill-down cards.

## 5. Connecting to Existing Experiments (`gert connect`)

GERT allows users to attach the monitoring TUI to historical or currently running experiments without needing to memorize complex IDs. Instead of requiring an explicit `experiment_id` and `execution_id`, the user simply provides the original configuration file.

*   **Command:** `gert connect <config.json> [OPTIONS]`
*   **Discovery:** The CLI reads the `config.json` to determine the experiment `name` and the `storage_base` (permanent storage directory). It scans this directory to discover all previous and ongoing executions associated with this experiment.
*   **Server Lifecycle:** The TUI relies entirely on the GERT server's REST API for all data. If a GERT server is not currently running at the specified `--api-url`, the `gert connect` command **must temporarily spawn a standard background server**. This is exactly the same generic experiment server started by `gert server` or `gert run`. It relies on the server's existing functionality to load state from the local permanent storage. It should never circumvent the API to read parquet/json files directly from disk.
*   **Entry Point:** Unlike `gert run --monitor` (which launches directly into the newly started execution's dashboard), `gert connect` launches at the **Execution Browser View**, displaying all executions sorted newest to oldest.
*   **Offline/Completed Experiments:** Once an execution is selected, the monitor loads perfectly via the API, even if the run is fully complete or failed. It retrieves the static terminal state, parses the final datasets, and allows the user to browse logs and plot data exactly as if it had just finished running.
*   **Persistence:** The TUI opened by `gert connect` remains open until explicitly closed by the user (via `q` or `ctrl+c`), regardless of whether the underlying experiment finishes its execution while the monitor is attached.
