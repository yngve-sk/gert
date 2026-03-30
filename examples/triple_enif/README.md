# Triple EnIF Example

This example demonstrates a sequential data assimilation workflow using the Ensemble Information Filter (EnIF).

## Overview

The experiment performs 3 EnIF updates in a row.
Each iteration:
1. Runs a simple polynomial forward model ($y = x^2 + 10$).
2. Performs an EnIF update to move parameters toward explaining the observation ($y=100$).

## Files
- `experiment.json`: The GERT configuration file defining the 3-step update schedule.
- `simple_polynomial.py`: A basic forward model that computes a response and pushes it to GERT.

## Running the Example

From the project root:

```bash
python -m gert run examples/triple_enif/experiment.json --wait
```

This will:
- Register the experiment.
- Start the execution.
- Run Iteration 0 (Forward Models).
- Run Update 1 (EnIF).
- Run Iteration 1 (Forward Models).
- Run Update 2 (EnIF).
- Run Iteration 2 (Forward Models).
- Run Update 3 (EnIF).
- Run Iteration 3 (Final Forward Models).
- Display the final consolidated responses.
