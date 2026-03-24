# Simple GERT Example

This directory contains a basic example of how to configure and run an experiment using the GERT server with a realistic executable forward model.

## Files

* `simple_polynomial.py`: A simulated mathematical model (e.g., polynomial). It takes standard arguments (`--experiment-id`, `--realization`, `--iteration`) and pushes a computed "FOPR" response back to the GERT API.
* `experiment.json`: The GERT configuration file. It defines the parameter matrix (3 realizations), the forward model step (pointing to `simple_polynomial.py`), and the queue configuration (`local`).

## How to Run

### 1. Start the GERT Server
In a terminal (from the project root), start the server using the GERT CLI:
```bash
uv run gert server --reload
```

### 2. Run the Experiment
Open another terminal and use the CLI to run the experiment.
> **Important:** Before running, you must ensure the `executable` path in `experiment.json` is absolute for your machine, or keep it as `"simple_polynomial.py"` if you have it in your `$PATH`.

```bash
uv run gert run examples/simple/experiment.json
```

This will automatically:
1. Register the experiment with the server.
2. Start the execution loop.
3. Provide you with the URL to query the consolidated responses.

### 3. Query the Consolidated Responses
Wait a few seconds for the local jobs to finish, then fetch the results using `curl` and the execution ID printed by the `run` command (e.g., `xyz-789`):
```bash
curl http://localhost:8000/storage/xyz-789/responses
```

You should see the consolidated results from all 3 realizations.
