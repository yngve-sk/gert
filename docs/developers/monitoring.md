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
    *   **Interactive Tree:** A navigable tree widget with the structure `Experiment -> Iteration -> Realization`. This allows the user to drill down into the specific parts of the experiment.
    *   **Response Viewer:** When a user selects a realization in the tree, this view will display the content of the last response JSON received for that specific realization, providing immediate insight into its output.

## Recommended Tooling

*   **Textual:** The TUI will be built exclusively with the `textual` framework. Its advanced features for complex layouts, widget library (`DataTable`, `Tree`, `ProgressBar`), and robust event handling system are essential for creating the rich, interactive experience required for the monitor.

## Data Model
All monitoring data adheres to GERT's immutable configuration pattern. The execution state is strictly observable and can never be modified through the monitoring interface.

## Implementation Status
- [ ] Backend monitoring APIs
- [ ] TUI monitor application (`textual`)
- [ ] Web GUI interface (future)
