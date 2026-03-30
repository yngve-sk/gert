# Slow Triple EnIF Example

This example demonstrates a sequential data assimilation workflow using a "slow" forward model that emits responses incrementally.

## Overview

The experiment performs 3 EnIF updates in a row.
Each iteration:
1. Runs a slow forward model ($y = x^2 + 10 + step$) that takes ~20-30 seconds.
2. The model emits responses at every 1-second interval.
3. Performs an EnIF update at the end of the iteration using the response at `step=20`.

## Files
- `experiment.json`: The GERT configuration file defining the 3-step update schedule and 20 realizations.
- `slow_polynomial.py`: A forward model that simulates a time-consuming process.

## Running the Example

From the project root:

```bash
python -m gert run examples/slow_triple_enif/experiment.json --monitor
```

Using the `--monitor` flag will launch the Textual-based dashboard, allowing you to:
- See progress bars for multiple iterations.
- Expand iterations in the tree to see individual realization statuses.
- Select a realization to see its latest emitted response and value.
