---
name: gert-tui-developer
description: Guidelines and specifications for the GERT Textual User Interface (TUI). Use this skill when modifying the monitor (src/gert/monitor.py), the plotter (src/gert/plotter.py), or any interactive CLI components.
---

# GERT TUI Developer

This skill provides the UX standards and technical rules for the GERT terminal monitoring interface.

## Core References

When modifying or adding new TUI components, use the `read_file` tool to consult the following repository documentation:

- **docs/developers/monitoring_views.md**: The exact information architecture, metrics definitions (like `sum abs misfit`), and expected layouts for the various screens (Experiment, Iteration, Realization, Step).
- **docs/developers/monitoring.md**: Guidelines on how the asynchronous `Textual` app should poll the REST API without blocking the UI thread.
- **docs/developers/plotting.md**: Rules for generating line charts and scatter heatmaps within the terminal using `textual-plot`, including data caching and "small multiples" behavior.

Always consult these references before altering the visual layout or the data-fetching loops to avoid breaking the asynchronous reactivity of the UI.
