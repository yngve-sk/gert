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
    parser.add_argument("--step-name", required=True)
    parser.add_argument("--api-url", default="http://localhost:8000")
    args = parser.parse_args()

    client = GertForwardModelClient(
        api_url=args.api_url,
        experiment_id=args.experiment_id,
        execution_id=args.execution_id,
        iteration=args.iteration,
        realization_id=args.realization,
        source_step=args.step_name,
    )

    with client.run():
        # Sleep to simulate forward model step
        time.sleep(0.5)

        # 1. Read input parameters from current workdir
        param_file = Path("parameters.json")
        if param_file.exists():
            params = json.loads(param_file.read_text(encoding="utf-8"))
            x = float(params.get("MULTFLT", 1.0))
        else:
            x = float(args.realization)

        # Execute the "Math" (y = x + iteration + realization + step_index)
        # Extract numeric index from step_0, step_1...
        try:
            step_idx = int(args.step_name.split("_")[-1])
        except ValueError:
            step_idx = 0

        computed_value = float(x + args.iteration + args.realization + step_idx)

        # 3. Ingest results via SDK
        client.post_response(
            key={"response": f"R_{args.step_name}"},
            value=computed_value,
        )


if __name__ == "__main__":
    main()
