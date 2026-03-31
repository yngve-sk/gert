#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from gert.plugins.forward_model_client import GertForwardModelClient


def main() -> None:
    parser = argparse.ArgumentParser(
        description="A simple polynomial forward model for GERT.",
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

    client = GertForwardModelClient(
        api_url=args.api_url,
        experiment_id=args.experiment_id,
        execution_id=args.execution_id,
        iteration=args.iteration,
        realization_id=args.realization,
        source_step="simple_polynomial",
    )

    with client.run():
        # 1. Read input parameters from current workdir
        param_file = Path("parameters.json")
        if param_file.exists():
            params = json.loads(param_file.read_text(encoding="utf-8"))
            x = float(params.get("MULTFLT", 1.0))
        else:
            # Fallback for manual testing
            print("[Polynomial Model] parameters.json not found, using realization x")
            x = float(args.realization)

        # Execute the "Math" (y = x^2 + 10)
        computed_value = float(x**2 + 10)

        print(
            f"[Polynomial Model] Realization {args.realization} computed FOPR = "
            f"{computed_value}. Sending to {args.api_url}...",
        )

        # 3. Ingest results via SDK
        client.post_response(
            key={"response": "FOPR"},
            value=computed_value,
        )

        print(
            f"[Polynomial Model] Realization {args.realization} successfully ingested.",
        )


if __name__ == "__main__":
    main()
