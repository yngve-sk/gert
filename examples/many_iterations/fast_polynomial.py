#!/usr/bin/env python3
import argparse
import json
import sys
import time
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(
        description="A fast polynomial forward model for GERT with a 2s sleep.",
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

    # Simulate work (2 seconds)
    time.sleep(2.0)

    # 1. Read input parameters from current workdir
    param_file = Path("parameters.json")
    if param_file.exists():
        params = json.loads(param_file.read_text(encoding="utf-8"))
        x = float(params.get("MULTFLT", 1.0))
    else:
        x = float(args.realization)

    # Execute the "Math" (y = x^2 + 10)
    computed_value = float(x**2 + 10)

    payload = {
        "realization": args.realization,
        "source_step": "fast_polynomial",
        "key": {"response": "FOPR"},
        "value": computed_value,
    }

    ingest_url = (
        f"{args.api_url}/experiments/{args.experiment_id}/executions/"
        f"{args.execution_id}/ensembles/{args.iteration}/ingest"
    )

    try:
        response = httpx.post(ingest_url, json=payload)
        response.raise_for_status()
    except httpx.HTTPError as e:
        print(
            f"[Fast Model] Realization {args.realization} failed to ingest: {e}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
