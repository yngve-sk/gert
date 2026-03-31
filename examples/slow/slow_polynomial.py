#!/usr/bin/env python3
import argparse
import json
import time
from pathlib import Path

from gert.plugins.forward_model_client import GertForwardModelClient


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--execution-id", required=True)
    parser.add_argument("--realization", type=int, required=True)
    parser.add_argument("--iteration", type=int, required=True)
    parser.add_argument("--api-url", default="http://localhost:8000")
    args = parser.parse_args()

    client = GertForwardModelClient(
        api_url=args.api_url,
        experiment_id=args.experiment_id,
        execution_id=args.execution_id,
        iteration=args.iteration,
        realization_id=args.realization,
        source_step="slow_polynomial",
    )

    with client.run():
        # Sleep to simulate slow forward model
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

        # 3. Ingest results via SDK
        client.post_response(
            key={"response": "FOPR"},
            value=computed_value,
        )


if __name__ == "__main__":
    main()
