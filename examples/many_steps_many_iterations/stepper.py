#!/usr/bin/env python3
import argparse
import contextlib
import json
import sys
import time
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(
        description="A generic step-model for GERT.",
    )
    parser.add_argument(
        "--step-name",
        required=True,
        help="The name of this step",
    )
    parser.add_argument(
        "--experiment-id",
        required=True,
        help="The GERT experiment ID",
    )
    parser.add_argument(
        "--execution-id",
        required=True,
        help="The GERT execution ID",
    )
    parser.add_argument(
        "--realization",
        required=True,
        type=int,
        help="The realization number",
    )
    parser.add_argument(
        "--iteration",
        required=True,
        type=int,
        help="The iteration number",
    )
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="Base URL of the GERT server",
    )

    args = parser.parse_args()

    print(
        f"[{args.step_name}] Starting realization {args.realization} "
        f"iteration {args.iteration}",
    )
    print(f"[{args.step_name}] Working hard...", file=sys.stderr)

    # Simulate work (0.2 seconds)
    time.sleep(0.2)

    # Read input parameters from current workdir
    param_file = Path("parameters.json")
    x = 1.0
    if param_file.exists():
        params = json.loads(param_file.read_text(encoding="utf-8"))
        x = float(params.get("MULTFLT", 1.0))

    # Emit a response specific to this step.
    # The value is calculated using x, step_index and iteration.
    step_index = 0
    if args.step_name.startswith("step_"):
        with contextlib.suppress(ValueError, IndexError):
            step_index = int(args.step_name.split("_")[1])

    computed_value = float(x * (step_index + 1) + args.iteration)

    payload = {
        "realization": args.realization,
        "source_step": args.step_name,
        "key": {"response": f"R_{args.step_name}"},
        "value": computed_value,
    }

    ingest_url = (
        f"{args.api_url}/experiments/{args.experiment_id}/executions/"
        f"{args.execution_id}/ensembles/{args.iteration}/ingest"
    )

    try:
        response = httpx.post(ingest_url, json=payload)
        response.raise_for_status()
        print(f"[{args.step_name}] Successfully ingested response: {computed_value}")
    except httpx.HTTPError as e:
        print(
            f"[{args.step_name}] Realization {args.realization} failed to ingest: {e}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
