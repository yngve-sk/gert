#!/usr/bin/env python3
import argparse
import sys

import httpx


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

    # Simulate a polynomial model: response = 100 + 10 * realization^2
    computed_value = float(100 + 10 * (args.realization**2))

    payload = {
        "realization": args.realization,
        "source_step": "simple_polynomial",
        "key": {"response": "FOPR"},
        "value": computed_value,
    }

    print(
        f"[Polynomial Model] Realization {args.realization} computed FOPR = "
        f"{computed_value}. Sending to {args.api_url}...",
    )

    ingest_url = f"{args.api_url}/storage/{args.experiment_id}/ingest"

    try:
        response = httpx.post(ingest_url, json=payload)
        response.raise_for_status()
        print(
            f"[Polynomial Model] Realization {args.realization} successfully ingested.",
        )
    except httpx.HTTPError as e:
        print(
            f"[Polynomial Model] Realization {args.realization} failed to ingest: {e}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
