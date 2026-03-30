# Many Iterations Example

This example demonstrates a long-running sequential data assimilation workflow.

## Overview

The experiment performs 19 sequential EnIF updates (Total 20 iterations).
Each iteration:
1. Runs a polynomial forward model that sleeps for 2 seconds.
2. Performs an EnIF update.

This is ideal for stress-testing the monitor UI with many progress bars and a large tree of realizations.

## Running the Example

From the project root:

```bash
python -m gert run examples/many_iterations/experiment.json --monitor
```
