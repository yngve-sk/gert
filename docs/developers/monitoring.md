# GERT Monitoring Architecture

## Overview
GERT provides real-time monitoring of experiment execution through a clean separation of concerns: data collection, API exposure, and a rich terminal user interface (TUI).

## Design Principles
* **Domain Agnostic:** The monitoring layer reports on generic execution states (e.g., `RUNNING`, `SUCCESS`, `FAILED`), not domain-specific outputs.
* **Interface Separation:** The backend monitoring API is completely independent of the presentation layer.
* **Extensible:** The design supports multiple presentation interfaces, with the TUI being the primary focus.
* **Real-time:** The architecture favors real-time data streaming (e.g., WebSockets, SSE) to power the live TUI, avoiding inefficient polling.

## Components

### 1. Monitoring API
A set of `FastAPI` endpoints responsible for exposing execution status, job progress, and summary statistics. This is the single source of truth for the monitoring TUI.

### 2. TUI Monitor (Textual Application)
A full-featured Terminal User Interface application for interactive, real-time experiment monitoring.

#### Key Features & Layout
The application will be built using a multi-pane layout:

*   **Status & Progress View (Top Pane):**
    *   **Per-Iteration Progress:** Displays a dedicated progress bar for each iteration, which fills as its associated realizations are completed.
    *   **State Summary:** A dynamic counter that shows the aggregate number of realizations currently in each state across the entire experiment (e.g., `PENDING: 10, RUNNING: 8, COMPLETED: 32, FAILED: 2`).

*   **Navigation & Detail View (Bottom Pane):**
    *   **Hierarchical Navigation (Tree/Table):** A navigable widget with the structure `Experiment -> Iteration -> Realization -> Step`. This allows the user to drill down into the specific parts and execution steps of the experiment.
    *   **Mathematical Updates:** To accurately reflect the experiment's macro flow, mathematical update steps must be explicitly represented in the tree view. They should appear in between iterations (e.g., after the realizations of Iteration 0 and before Iteration 1). Selecting an update node should display its status, logs (`stdout`/`stderr`), and execution details in the Detail Viewer.
    *   **Update Storage & API:**
        *   **Storage Location:** Update metadata and logs for iteration `i` (which produces the iteration `i+1` parameters) must be stored within the directory of its posterior ensemble: `iter-{i+1}/`.
        *   **UpdateMetadata Model:** A dedicated `UpdateMetadata` Pydantic model will track the algorithm name, its configuration arguments, execution status (`RUNNING`, `COMPLETED`, `FAILED`), timing/error information, and mathematical metrics (e.g., prior variance, posterior variance).
        *   **API Exposure:** A new endpoint `GET /experiments/{exp_id}/executions/{exec_id}/ensembles/{it}/update/metadata` will provide this information, allowing the monitor to display both the progress and the mathematical summary of the update.
    *   **Expand All:** A shortcut key ('e') is provided to expand/collapse all realizations, showing all forward model steps at once.
    *   **Detail Viewer (Response/Logs):**
        *   **Realization Selected:** Displays the content of the last response JSON received for that specific realization.
        *   **Step Selected:** Displays the `stdout` and `stderr` logs for the selected step, along with its status and timing information.

## Monitoring API & Data Model

### Data Model
The monitoring state is expanded to include step-level granularity:

```python
class StepStatus(BaseModel):
    name: str
    status: str  # PENDING, RUNNING, COMPLETED, FAILED
    start_time: datetime | None = None
    end_time: datetime | None = None

class RealizationStatus(BaseModel):
    realization_id: int
    iteration: int
    status: str
    steps: list[StepStatus] = []
```

### Endpoints
*   `GET /experiments/{exp_id}/executions/{exec_id}/status`: Returns a list of `RealizationStatus` including their associated steps.
*   `GET /experiments/{exp_id}/executions/{exec_id}/realizations/{r_id}/steps/{step_name}/logs`: Retrieves the `stdout` and `stderr` for a specific step.

## Forward Model Step Execution Monitoring

To capture step-level status and logs without requiring a resident agent on compute nodes, GERT's job submission layer (utilizing `psij-python`) generates an execution wrapper or a multi-step shell script. This wrapper is responsible for:

1.  **State Signaling:** Emitting an HTTP request to the GERT Monitoring API when a step starts (`RUNNING`) and finishes (`COMPLETED` or `FAILED`).
2.  **Output Redirection:** Redirecting the `stdout` and `stderr` of each step to unique, deterministic log files within the realization's workdir (e.g., `step_0_stdout.log`, `step_0_stderr.log`).
3.  **Error Propagation:** Ensuring that the failure of any step is correctly captured and reported to the orchestrator.

## Recommended Tooling

*   **Textual:** The TUI will be built exclusively with the `textual` framework. Its advanced features for complex layouts, widget library (`DataTable`, `Tree`, `ProgressBar`), and robust event handling system are essential for creating the rich, interactive experience required for the monitor.

## Data Model
All monitoring data adheres to GERT's immutable configuration pattern. The execution state is strictly observable and can never be modified through the monitoring interface.

## Implementation Status
- [ ] Backend monitoring APIs
- [ ] TUI monitor application (`textual`)
- [ ] Web GUI interface (future)
