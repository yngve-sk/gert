#!/usr/bin/env python3
# ruff: noqa: S311
import argparse
import random
import sys
import time

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(
        description="A slow polynomial forward model for GERT.",
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
        "--ensemble-id",
        required=True,
        type=str,
        help="The ensemble ID",
    )
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="Base URL of the GERT server",
    )

    args = parser.parse_args()

    # Simulate a slow process (20-30 seconds total)
    total_time = random.uniform(20.0, 30.0)
    print(
        f"[Slow Model] Realization {args.realization} running for {total_time:.2f}s...",
    )

    elapsed_time = 0.0
    step = 0
    ingest_url = (
        f"{args.api_url}/storage/{args.experiment_id}"
        f"/ensembles/{args.ensemble_id}/ingest"
    )

    while elapsed_time < total_time:
        # Sleep for ~1 second with some jitter
        step_sleep = random.uniform(0.8, 1.2)
        if elapsed_time + step_sleep > total_time:
            step_sleep = total_time - elapsed_time
        time.sleep(step_sleep)
        elapsed_time += step_sleep
        step += 1

        # Simulate a polynomial model evolving over time
        computed_value = float(100 + 10 * (args.realization**2) + step)

        payload = {
            "realization": args.realization,
            "source_step": "slow_polynomial",
            "key": {"response": "FOPR", "step": str(step)},
            "value": computed_value,
        }

        print(
            f"[Slow Model] Realization {args.realization} (step {step}) "
            f"computed FOPR = {computed_value}. Sending to {args.api_url}...",
        )

        try:
            response = httpx.post(ingest_url, json=payload)
            response.raise_for_status()
            print(
                f"[Slow Model] Realization {args.realization} step {step} "
                "successfully ingested.",
            )
        except httpx.HTTPError as e:
            print(
                f"[Slow Model] Realization {args.realization} failed to "
                f"ingest step {step}: {e}",
                file=sys.stderr,
            )
            sys.exit(1)


if __name__ == "__main__":
    main()
