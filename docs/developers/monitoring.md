# GERT Monitoring Architecture

## Overview
GERT provides real-time monitoring of experiment execution through a clean separation of concerns: data collection, API exposure, and presentation interfaces.

## Design Principles
* **Domain Agnostic:** The monitoring layer will report on generic execution states (e.g., `RUNNING`, `SUCCESS`, `FAILED`), job progress, and resource metrics, not domain-specific outputs.
* **Interface Separation:** The backend monitoring API is completely independent of any presentation layer. Multiple interfaces can consume the same API.
* **Extensible:** The design supports multiple presentation interfaces (e.g., CLI, Web GUI) sharing the same underlying data model and API.
* **Real-time:** The architecture favors real-time data streaming (e.g., WebSockets, SSE) for live updates, avoiding inefficient polling where possible.

## Components

### 1. Monitoring API
A set of `FastAPI` endpoints responsible for exposing execution status, job progress, and resource metrics. This is the single source of truth for all monitoring clients.

### 2. CLI Monitor
A terminal-based live dashboard that provides a real-time view of the experiment, inspired by the live output of a CI/CD pipeline like GitHub Actions.

#### Key Features
*   **Live Status Table:** A top-level view showing the status of all realizations (`PENDING`, `RUNNING`, `COMPLETED`, `FAILED`).
*   **Interactive Drill-Down:** The ability for a user to select a specific realization.
*   **Live Plotting:** When a realization is selected, the CLI will display a live-updating chart for a chosen response key. The user should be able to cycle through available response keys and realizations using keyboard shortcuts.
*   **Log Streaming:** View the live `stdout`/`stderr` from the forward model process for a selected realization.

### 3. Future Web GUI
A potential future browser-based interface that would consume the very same monitoring APIs to provide a richer graphical experience.

## Recommended Tooling

*   **Rich:** For the initial implementation of the CLI monitor, the `rich` library is highly recommended. Its `Live` display capabilities are ideal for rendering the main status table and updating it without flicker. Its built-in table, progress bar, and spinner components will accelerate development.
*   **Textual:** If the CLI monitor's interactivity needs evolve to require more complex layouts, clickable widgets, or advanced application-like behavior, the `textual` library (from the same author as `rich`) would be the next logical step.

## Data Model
All monitoring data adheres to GERT's immutable configuration pattern. The execution state is strictly observable and can never be modified through any monitoring interface.

## Implementation Status
- [ ] Backend monitoring APIs
- [ ] CLI monitor interface
- [ ] Web GUI interface (future)
