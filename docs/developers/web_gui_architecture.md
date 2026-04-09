# GERT Web GUI Architecture & Specification

## 1. Core Philosophy & Persona
The GERT GUI is built for **Geologists, Geophysicists, and Reservoir Engineers**.
* **Primary Use Case:** History Matching, Data Assimilation (EnKF/ES-MDA), and Uncertainty Quantification.
* **Design Language:** **"Scientific Workbench"** — Dense, data-rich, and highly mathematical.
    * **Zero-Waste Layout:** Prioritize information density over whitespace. Use compact padding/margins.
    * **Dark Mode Primacy:** High-contrast Dark Mode is the default. Heatmaps and spatial fields are more legible against dark backgrounds.
* **Theming:** The UI utilizes the **Skeleton UI** component library on top of **Tailwind CSS**.
    * **Centralized Theme:** Configured via CSS custom properties. **Rule:** Never hardcode literal colors (e.g., `#ff0000`); always use semantic tokens (e.g., `bg-surface-100-800-token`, `text-primary-500`, `bg-error-500`).
    * **Theming Hierarchy (Semantic Surfaces):**
        * **L0: Ground (`bg-surface-900`):** The absolute background. Used for the outermost app shell and inter-panel gutters.
        * **L1: Panel (`bg-surface-800`):** Primary structural panels (Sidebars, Header, Workspace background).
        * **L2: Container (`bg-surface-700`):** Elevated widgets within panels (Plot containers, Data cards, Tab bodies).
        * **L3: Inset (`bg-surface-600`):** High-density grouping within containers (Control bars, Fieldsets, Active/Hover states).
    * **Semantic Accents (Action Hierarchy):**
        * **Primary:** Core DA actions (Start, Resume, Save).
        * **Secondary:** Navigation and State (Active Tabs, Selected Tree Nodes).
        * **Tertiary:** Contextual metadata and tooltips.
    * **Typography:** Monospaced fonts (e.g., `JetBrains Mono`) for all numerical data, parameter tables, and misfits to ensure vertical alignment of decimals.

## 2. Technical Stack
* **Language:** **TypeScript** (Strict mode required for all components and stores).
* **Framework:** SvelteKit (Static Adapter for bundled SPA delivery).
* **Styling:** Tailwind CSS + Skeleton UI.
* **Plotting (Pluggable):**
    * **uPlot:** For high-performance info-vis, timeseries, and standard 1D line/scatter plots.
    * **D3.js:** For highly custom, bespoke SVG or Canvas-based visualizations.
    * **deck.gl:** For WebGL-powered 2D/3D spatial field visualizations, specifically optimized for large Parquet-backed datasets.
* **Backend:** GERT FastAPI Server (`src/gert/server/router.py`).

## 3. Project Structure & Organization
The frontend source lives in a dedicated root-level directory:
* **Source Folder:** `/svelte_gui`
* **Internal Structure:** Standard SvelteKit (Vite-based) project.
* **Component Library:** Skeleton UI v2+ with Tailwind CSS.

## 4. Distribution & Packaging
GERT aims for a "zero-config" web interface accessible via standard Python installation (`pip install gert`).

* **Build Workflow:**
    1. The Svelte project is compiled into a Single Page Application (SPA).
    2. The build output is injected directly into the Python source tree at `src/gert/server/static/`.
    3. Vite `outDir` must be configured to point to this directory.
* **Python Integration:**
    * The `pyproject.toml` must include `src/gert/server/static` as package data to ensure it is bundled into the Python Wheel (.whl).
    * The FastAPI server (`gert_server.py`) mounts this directory using `StaticFiles` and implements a catch-all route to serve `index.html` for SPA routing compatibility.
* **User Access:**
    * Users launch the GUI via the CLI: `gert ui`.
    * This command starts the FastAPI server on a free port and automatically opens the user's default web browser using the Python `webbrowser` module.

## 5. UI Layout & Navigation Architecture
The GUI follows a "Workbench" pattern to support the Level 1-5 drill-down:
* **Permanent Navigation Sidebar (Left):** A hierarchical Tree View allowing instant access to different Experiments and Executions.
* **Contextual Detail Sidebar (Right):** A collapsible "Properties" pane that displays detailed JSON metadata or parameter values for whichever node is currently selected in the center workspace.
* **Multi-Tab Workspace (Center):** The primary area for visualizations. Users can open multiple "Analysis" tabs (e.g., one for a deck.gl spatial grid, one for a uPlot misfit curve) and switch between them.

## 4. Pluggable Plotting Architecture
To ensure high-performance interactivity while handling massive ensemble datasets, the GUI must utilize a library-agnostic plotting strategy:

* **Generic Plot Container:** Plotting views must be implemented as a generic `PlotContainer.svelte` component. It manages resizing, cross-ensemble data orchestration, and common UI controls.
* **Plotter Dispatcher:** The UI must implement a dispatcher that automatically matches data to the appropriate plotter engine based on metadata/dimensionality:
    * **1D / Scalar / Timeseries:** Dispatch to **uPlot**.
    * **2D Surface / 3D Volumetric Field:** Dispatch to **deck.gl**.
    * **Bespoke / Multi-dimensional Topology:** Dispatch to **D3.js**.
* **Standard Interface:** Every plotter engine (e.g., `UPlotEngine.svelte`) must implement a shared TypeScript interface:
  ```typescript
  interface PlotterProps {
    data: any;           // The sliced Parquet/JSON data
    schema: Schema;      // Metadata describing columns/dimensions
    options: PlotOptions; // View-specific config (colors, scales)
    onHover?: (point: any) => void;
  }
  ```
* **Real-Time Data Injection:** Plotters must support partial updates (appending points) to enable live-viewing while forward models are actively running.

## 5. Communication & Resilience
* **Log Streaming:** The frontend must consume the `/logs/stream` endpoint using the **ReadableStream API (fetch Reader)**. It should update a virtualized terminal component line-by-line without waiting for the full response to close.
* **WebSocket Resilience:** The singleton WebSocket connection must implement an automatic **reconnection strategy** with exponential backoff. The UI should display a non-blocking "Disconnected/Reconnecting" toast/indicator when the stream is interrupted.
* **Environment Configuration:** **Zero Hardcoded URLs.** All API and WebSocket base URLs must be resolved via a centralized `config.ts` or SvelteKit environment variables.

## 6. SvelteKit Routing Structure
The application should follow a strict nested routing structure mirroring the backend REST API:

```text
src/routes/
├── +page.svelte                                  # Redirects to /experiments
├── experiments/
│   ├── +page.svelte                              # Level 1: List all experiments
│   └── [exp_id]/
│       ├── +layout.svelte                        # Shared layout/context for an experiment
│       ├── +page.svelte                          # Level 2: List executions (Start/Pause/Resume)
│       └── executions/[exec_id]/
│           ├── +layout.svelte                    # Shared layout for an active/historical execution
│           ├── +page.svelte                      # Level 3: Iterations dashboard (Progress, Convergence)
│           ├── analysis/                         # Advanced Plotting Views
│           │   ├── misfits/+page.svelte          # Misfit & Observation Overlay
│           │   ├── parameters/+page.svelte       # Parameter Evolution & Spatial Grids
│           │   └── cross-ensemble/+page.svelte   # Prior vs Posterior comparisons
│           └── ensembles/[iteration]/
│               └── realizations/[r_id]/
│                   └── steps/[step_name]/
│                       └── +page.svelte          # Level 5: Step Details & Live Logs terminal
```

## 7. Data & State Management
* **Strict Iteration Separation:** The backend API (`/ensembles/{iteration}/...`) strictly separates iterations. The frontend is fully responsible for fetching Prior (Iteration 0) and Posterior (Iteration N) data independently, joining them locally, and overlaying them in the plotting components.
* **Pagination & Slicing:** Never fetch raw Parquet blobs entirely into memory. Use query parameters (`?columns=X&realization=Y`) to fetch exact slices needed for the current chart.
* **Real-Time State (WebSockets):**
  * The frontend must maintain a singleton WebSocket connection to `WS /experiments/{id}/executions/{exec_id}/events`.
  * Incoming events should update a global Svelte `writable` store, allowing progress bars and execution statuses to reactively update anywhere in the component tree without HTTP polling.
* **Local Development:** Vite (`vite.config.ts`) must be configured to proxy `/api` and `/ws` requests to the local FastAPI server (default `http://127.0.0.1:8000`) to enable Hot Module Replacement (HMR) without CORS violations.

## 9. Testing Strategy
To ensure stability and reliability, the GERT Web GUI follows a strict testing hierarchy.

### 9.1 Zero-Mock Integration Policy
**The GUI must never mock the GERT API.** Mocking the complex nested resource hierarchy and real-time WebSocket streams of GERT is brittle and difficult to maintain.
* **Test Environment:** All integration tests must spin up a live GERT FastAPI server instance using a temporary `permanent_storage` directory.
* **Data Source:** Tests should utilize standard experiment examples (e.g., `examples/simple`) to generate predictable state.

### 9.2 End-to-End Testing (Playwright)
The primary verification layer is **Playwright**.
* **Navigation & Drill-down:** Verify that clicking nodes in the hierarchical Tree correctly updates the URL and mounts the corresponding nested routes.
* **Execution Flow:** Verify that the "Start", "Pause", and "Resume" buttons correctly trigger backend transitions and reflect status changes in the UI.
* **WebSocket Reactivity:** Inject status events into the live server and verify that the UI (progress bars, node labels) updates instantly without page refreshes.
* **Log Streaming:** Verify that the virtualized terminal correctly tails active logs via the `ReadableStream` API.
* **Plotting Stability:** Verify that canvas/WebGL elements (deck.gl) correctly mount and do not crash the browser when large Parquet slices are loaded.

### 9.3 Unit Testing (Vitest)
Unit tests focus on non-visual logic. Avoid "tautological" tests (e.g., testing if a button renders).
* **Data Transformation:** Test the logic that joins Prior and Posterior iterations into the cross-ensemble plotter format.
* **Plotter Dispatcher:** Verify that the dispatcher correctly selects `uPlot` vs `deck.gl` based on data dimensionality.
* **Svelte Stores:** Test the WebSocket store logic, ensuring correct handling of "history replay" versus "live updates."

### 9.4 Resilience & Edge Cases
* **Network Interruption:** Simulate a server crash during a Playwright run and verify the UI displays the "Reconnecting" indicator and successfully restores state upon server reboot.
* **Concurrency:** Verify UI stability when receiving a high-frequency burst of WebSocket events (e.g., 100 realizations completing simultaneously).
* **OOM Prevention:** Test the UI's behavior when a user attempts to select an excessively large column without appropriate slicing.

## 10. Implementation Steps (Planned)
