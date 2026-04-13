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
* **Framework:** **Svelte 5** (Strictly use **Runes** for state management: `$state`, `$derived`, `$effect`. Do not use legacy Svelte 3/4 syntax).
* **Router:** SvelteKit (Static Adapter for bundled SPA delivery).
* **Styling:** Tailwind CSS + Skeleton UI.
* **Plotting (Pluggable):**
    * **uPlot:** For high-performance info-vis, timeseries, and standard 1D line/scatter plots.
    * **D3.js:** For highly custom, bespoke SVG or Canvas-based visualizations.
    * **deck.gl:** For WebGL-powered 2D/3D spatial field visualizations, specifically optimized for large Parquet-backed datasets.
* **Backend:** GERT FastAPI Server (`src/gert/server/router.py`).

## 3. Engineering Standards (Linter & Type Checking)
To maintain the same high standards as the Python backend (ruff/mypy), the frontend strictly adheres to:

*   **Linter & Formatter:** **Biome** (all-in-one tool for linting and formatting).
    *   All code must be formatted and linted via `npx @biomejs/biome check --write`.
*   **Type Safety:**
    *   **TypeScript** (Strict mode enabled in `tsconfig.json`).
    *   `svelte-check` must be run to verify types across `.svelte` and `.ts` files.
    *   **Prohibited:** Use of `any`, `ts-ignore`, or `eslint-disable` (or Biome equivalents) without documented justification.
*   **Commit Hooks:** Frontend checks must be integrated into the repository's `pre-commit` workflow (via `npx @biomejs/biome check`).

## 4. Project Structure & Organization
The frontend source lives in a dedicated root-level directory:
* **Source Folder:** `/svelte_gui`
* **Internal Structure:** Standard SvelteKit (Vite-based) project.
* **Component Library:** Skeleton UI v2+ with Tailwind CSS.

## 5. Distribution & Packaging
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

## 6. UI Layout & Navigation Architecture
The GUI follows a "Workbench" pattern to support the Level 1-5 drill-down:
* **Permanent Navigation Sidebar (Left):** A hierarchical Tree View allowing instant access to different Experiments and Executions. Inside an Execution Inspector, this acts as the **Ensembles Dashboard**:
    * It displays a selectable, expandable list of Ensembles (Iterations) and interleaves "Update" steps.
    * Ensembles expand to show Realizations, which expand to show Forward Model Steps (sorted newest/currently executing at top, oldest at bottom).
    * Includes a **Server Status Panel** at the bottom showing uptime (incrementing in real-time), experiment counts, and versioning. This panel polls a dedicated `GET /health` endpoint every 5 seconds to provide a visual heartbeat/connection indicator.
* **Multi-Tab Workspace (Center):** The primary area for visualizations. Users can open multiple "Analysis" tabs and switch between them:
    * **Console:** Live and static log stream.
    * **Update Summary:** A global experiment overview visible when no specific node is selected. It features a lightweight `uPlot` line chart displaying algorithm convergence over time (e.g., Avg Misfit vs Variance). The X-axis represents discrete mathematical updates, formatted explicitly as `0→1`, `1→2`.
    * **Realization Status:** An aggregate view of realization progress bars. Filters to a specific Ensemble if one is selected in the sidebar, or shows all if none/all are selected. Realizations are shown as progress bars with text indicating `[Completed] / [Total]` steps, and the truncated name (4 chars, full on hover) of the active step. Selecting a realization syncs with the sidebar.
    * **Update Info:** Appears dynamically when an Update step is selected from the Ensembles Dashboard. Displays metadata, time used, discarded observations, and algorithm metrics. Metrics (such as variance or misfit) are intelligently grouped to show changes in a `Prior -> Posterior` format (e.g., "Variance: 1.00e+0 -> 5.00e-1"). It accommodates missing posterior data (which may only be available after the subsequent forward model pass).
    * **Analysis Tabs:** Specific visualization tabs (e.g., Responses, Observations) based on pluggable architecture.
    * **Step Details Page:** Clicking "Details" on a forward model step navigates to a new page (`/experiments/[id]/executions/[exec_id]/ensembles/[iter]/realizations/[real_id]/steps/[step_name]`) to show specific status and logs.

## 7. Pluggable Plotting Architecture
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

## 8. Communication & Resilience
* **Log Streaming & Filtering:** The frontend consumes the `/logs/stream` endpoint using the **ReadableStream API (fetch Reader)** to update a virtualized terminal line-by-line. It includes built-in reactive filters (INFO, DEBUG, WARN, ERROR) and a real-time text search input to parse the stream client-side without incurring backend search costs.
* **WebSocket Resilience:** The singleton WebSocket connection must implement an automatic **reconnection strategy** with exponential backoff. The UI should display a non-blocking "Disconnected/Reconnecting" toast/indicator when the stream is interrupted.
* **Environment Configuration:** **Zero Hardcoded URLs.** All API and WebSocket base URLs must be resolved via a centralized `config.ts` or SvelteKit environment variables.

## 9. Local Development Proxy
To avoid CORS issues during development, Vite must be configured (`vite.config.ts`) to proxy requests to the GERT FastAPI server:
```typescript
export default defineConfig({
	server: {
		proxy: {
			'/api': {
				target: 'http://127.0.0.1:8000',
				changeOrigin: true,
				rewrite: (path) => path.replace(/^\/api/, '')
			},
			'/ws': {
				target: 'ws://127.0.0.1:8000',
				ws: true
			}
		}
	}
});
```

## 10. SvelteKit Routing Structure
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

## 11. Data & State Management
* **Strict Iteration Separation:** The backend API (`/ensembles/{iteration}/...`) strictly separates iterations. The frontend is fully responsible for fetching Prior (Iteration 0) and Posterior (Iteration N) data independently, joining them locally, and overlaying them in the plotting components.
* **Pagination & Slicing:** Never fetch raw Parquet blobs entirely into memory. Use query parameters (`?columns=X&realization=Y`) to fetch exact slices needed for the current chart.
* **Real-Time State (WebSockets):**
  * The frontend must maintain a singleton WebSocket connection to `WS /experiments/{id}/executions/{exec_id}/events`.
  * Incoming events should update a global Svelte `writable` store, allowing progress bars and execution statuses to reactively update anywhere in the component tree without HTTP polling.
* **Local Development:** Vite (`vite.config.ts`) must be configured to proxy `/api` and `/ws` requests to the local FastAPI server (default `http://127.0.0.1:8000`) to enable Hot Module Replacement (HMR) without CORS violations.

## 12. Required User Stories
1. **Level 1 (Experiments):** As a user, I want to see an overview of all experiments in the workspace.
2. **Level 2 (Executions):** As a user, within a specific experiment, I want to see a list of all historical and active executions. I want to be able to start, pause, or resume an execution, and filter overarching experiment logs by severity level.
3. **Level 3 (Iterations):** As a user, within a specific execution, I want to see all data assimilation iterations (Prior, iter-1, etc.) and their convergence metrics (`ObservationSummary`).
4. **Level 4 (Forward Model Steps):** As a user, within a specific iteration, I want to see all individual forward model steps for each realization.
5. **Level 5 (Step Details & Logs):** As a user, when inspecting a specific step, I want to see runtime (duration), status, and live/historical logs (stdout/stderr via the `/logs/stream` endpoint).
6. **Cross-Ensemble Plotting:** As a user, I want to plot parameters and responses across ensembles (defaulting to Prior vs. Posterior). I need to see this *while* the forward model is actively running.
7. **Observation Overlay:** As a user, I want to see physical observations and simulated responses overlaid in the same view.
8. **Convergence Tracking:** As a user, I want a plot of misfits tracked over successive iterations.
9. **Spatial Grid Visualization:** As a user, if a grid is specified, I want to visualize the grid and see parameters/observations mapped spatially.

## 13. Testing Strategy
To ensure stability and reliability, the GERT Web GUI follows a strict testing hierarchy.

### 13.1 Zero-Mock Integration Policy
**The GUI must never mock the GERT API.** Mocking the complex nested resource hierarchy and real-time WebSocket streams of GERT is brittle and difficult to maintain.
* **Test Environment:** All integration tests must spin up a live GERT FastAPI server instance using a temporary `permanent_storage` directory.
* **Data Source:** Tests should utilize standard experiment examples (e.g., `examples/simple`) to generate predictable state.

### 13.2 End-to-End Testing (Playwright)
The primary verification layer is **Playwright**.
* **Navigation & Drill-down:** Verify that clicking nodes in the hierarchical Tree correctly updates the URL and mounts the corresponding nested routes.
* **Execution Flow:** Verify that the "Start", "Pause", and "Resume" buttons correctly trigger backend transitions and reflect status changes in the UI.
* **WebSocket Reactivity:** Inject status events into the live server and verify that the UI (progress bars, node labels) updates instantly without page refreshes.
* **Log Streaming:** Verify that the virtualized terminal correctly tails active logs via the `ReadableStream` API.
* **Plotting Stability:** Verify that canvas/WebGL elements (deck.gl) correctly mount and do not crash the browser when large Parquet slices are loaded.

### 13.3 Unit Testing (Vitest)
Unit tests focus on non-visual logic. Avoid "tautological" tests (e.g., testing if a button renders).
* **Data Transformation:** Test the logic that joins Prior and Posterior iterations into the cross-ensemble plotter format.
* **Plotter Dispatcher:** Verify that the dispatcher correctly selects `uPlot` vs `deck.gl` based on data dimensionality.
* **Svelte Stores:** Test the WebSocket store logic, ensuring correct handling of "history replay" versus "live updates."

### 13.4 Resilience & Edge Cases
* **Network Interruption:** Simulate a server crash during a Playwright run and verify the UI displays the "Reconnecting" indicator and successfully restores state upon server reboot.
* **Concurrency:** Verify UI stability when receiving a high-frequency burst of WebSocket events (e.g., 100 realizations completing simultaneously).
* **OOM Prevention:** Test the UI's behavior when a user attempts to select an excessively large column without appropriate slicing.

## 14. Implementation Roadmap (Milestones)

Building the "Scientific Workbench" follows a strict additive sequence.

**⚠️ MANDATORY WORKFLOW:** For each milestone, implementation is considered incomplete until:
1.  **Automated Tests:** Corresponding Vitest (logic) or Playwright (E2E) tests are implemented and passing.
2.  **Linting/Typing:** `npm run check` and `npm run lint` pass with zero warnings.
3.  **Visual Verification:** The UI is manually verified to adhere to the L0-L3 depth hierarchy and "Scientific Workbench" design language.

### Phase A: The Shell & Design System
*   **M1: Foundation Scaffolding:** Initialize `/svelte_gui` with SvelteKit (TypeScript), Tailwind CSS, and Skeleton UI. Set up the Static Adapter.
*   **M2: Industrial Dark Theme:** Implement the L0-L3 surface hierarchy and JetBrains Mono typography. Verify optical nesting in a dummy layout.
*   **M3: Layout Workbench:** Build the 3-pane responsive layout (Nav Sidebar, Multi-tab Workspace, Detail Drawer).

### Phase B: Connectivity & Navigation
*   **M4: API Proxy & Client:** Configure Vite proxy for local dev. Implement a centralized TypeScript API client with zero hardcoded URLs.
*   **M5: Experiment Browser (L1):** Build the Experiment List view. Implement routing to `/experiments/[id]`.
*   **M6: Execution Explorer (L2):** Build the Execution List for a selected experiment. Implement drill-down routing.

### Phase C: Reactivity & Control
*   **M7: WebSocket Pulse:** Implement the singleton WebSocket store with exponential backoff. Map events to a reactive Svelte store.
*   **M8: Execution Control:** Implement Start/Pause/Resume buttons. Build the Virtualized Terminal component using the `ReadableStream` API for live logs.
*   **M9: Iteration Dashboard (L3-4):** Build the hierarchical tree and macro-progress bars that update in real-time via the WebSocket store.

### Phase D: High-Density Analysis
*   **M10: Pluggable Plotting (uPlot):** Implement `PlotContainer.svelte` and the Plotter Dispatcher. Build the 1D uPlot engine for convergence/misfits.
*   **M11: Spatial Analysis (deck.gl):** Implement the WebGL deck.gl engine. Verify 2D/3D field rendering using Parquet-sliced datasets.

### Phase E: Production
*   **M12: Packaging & CLI:** Update `pyproject.toml` for static asset inclusion. Implement the `gert ui` command in `__main__.py` to launch and open the browser.
