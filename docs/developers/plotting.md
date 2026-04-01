# GERT Plotting Architecture

This document defines the architecture, user experience, and technical specifications for data visualization within GERT. Because GERT is domain-agnostic, the plotting engine must dynamically infer the appropriate visualization strategy based strictly on data dimensionality.

These specifications apply to the immediate Terminal User Interface (TUI) using `textual-plot`, as well as any future web-based GUI implementations.

## 1. User Experience (UX) Flow

The plotter is designed as an interactive overlay tightly coupled with the main navigation tree.

* **Activation:** The user presses the `p` (or `P`) key while highlighting a node in the navigation tree to open the Plotter Overlay. Pressing `p` again closes the overlay and returns focus to the tree.
* **Layout:** The plotting view utilizes a split-pane design:
  * **Left Pane (Selector):** A scrollable list of all available variables (both `parameters` and `responses`) relevant to the current scope. The user navigates this list using the `Up` and `Down` arrow keys.
  * **Right Pane (Canvas):** The interactive plotting canvas that renders the currently selected variable.

## 2. Contextual Scoping

The data fed into the plotting engine is strictly determined by the level of the hierarchy the user had selected when pressing `p`.

### Level A: Iteration Scope
Selecting an entire iteration (e.g., `Iteration 0`) and opening the plotter displays the **Ensemble View**.
* **Data:** Fetches the data for *all* realizations within that iteration.
* **Visualization:**
  * For 1D/Scalar data: Renders a **multiline plot** where each line represents a single realization's trajectory.
  * **Axis Selection:** The Y-axis is always the `value`. The X-axis is automatically inferred from available dimensions (e.g., `time`, `step`). If multiple potential X-axes exist, the UI must allow the user to cycle through them.
  * For 2D/3D spatial data: By default, shows the ensemble mean or allows the user to cycle through individual realization layers.

### Level B: Realization Scope
Selecting a specific realization (e.g., `Realization 42`) displays the **Realization View**.
* **Data:** Fetches all parameters and responses generated across the entire timeline of that specific realization.
* **Visualization:** Shows the evolution of the selected variable (e.g., `FOPR` over `time`) for the single realization. Selection of a specific parameter or response from the left pane is still required.

### Level C: Forward Model Step Scope
Selecting a specific step under a realization displays the **Step View**.
* **Data:** Same as the **Realization View**, but filtered to show *only* the responses and parameters that originated from or were utilized by that specific forward model step.
* **Visualization:** Provides a focused snapshot of the variables pertaining to that isolated execution phase.

## 3. Dimensionality & Agnostic Plotting Rules

The plotting engine does not know if a variable is "oil pressure", "temperature", or "porosity". It decides how to plot based entirely on the shape of the data.

### 1D / Scalar Series
When a variable consists of scalar values tracked over an index (e.g., time, step number, or depth):
* **Plot Type:** 2D Line Chart (or Scatter Plot).
* **Axes:**
  * **Y-Axis:** Strictly mapped to the `value`.
  * **X-Axis:** Mapped to any available dimension that is NOT the `value`. If multiple dimensions exist (e.g. both `time` and `measured_depth`), the user can cycle through them to redefine the X-axis.

### 2D Spatial Data
When a variable is a 2D matrix or grid (e.g., a surface permeability map):
* **Plot Type:** 2D Heatmap / Contour Plot.
* **Axes:** X and Y represent the spatial indices (e.g., `i`, `j` coordinates). Color intensity represents the `value`.

### 3D Spatial Data
When a variable is a 3D matrix (e.g., a full reservoir grid):
* **Plot Type:** Interactive 2D Heatmap with Z-Axis Slicing.
* **Interaction:** 3D data is rendered as a 2D slice. The UI must provide an interactive **Z-axis slider** (or layer selector keybindings like `<` and `>`) allowing the user to seamlessly scroll through the depth (K-index) of the matrix.

## 4. Implementation Guidelines (TUI)

For the immediate Terminal implementation within `gert.monitor`:
* **Library:** We use [`textual-plot`](https://pypi.org/project/textual-plot/) to power the terminal graphics. It supports braille-character drawing for high-resolution terminal line charts and scatter plots.
* **Data Fetching:** The plotter must use the existing `StorageAPI` endpoints. Data should be pivoted using `polars` before being handed to `textual-plot`.
* **Responsiveness:** Use a loading spinner for heavy ensemble loads to prevent blocking the UI.
