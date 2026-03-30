# Many Steps, Many Iterations Example

This example is designed to stress-test the GERT monitor UI and the orchestration engine. It features:

- **30 Forward Model Steps**: Each realization executes 30 sequential steps using a generic `stepper.py` script.
- **5 Iterations**: A total of 5 mathematical updates and 6 execution cycles (Prior + 5 Posterior evaluations).
- **10 Realizations**: A standard ensemble size for local testing.
- **Hierarchical Monitoring**: Ideal for testing the "Expand All" feature and step-level status tracking.
- **Log Capture**: Each step prints to `stdout` and `stderr` to verify the log-viewing capabilities.

## Running the Example

From the project root:

```bash
# Start the GERT server in one terminal
python -m gert server

# Run the experiment with the monitor in another terminal
python -m gert run examples/many_steps_many_iterations/experiment.json --monitor
```
