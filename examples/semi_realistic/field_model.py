#!/usr/bin/env python3
import argparse
import time
from pathlib import Path

import httpx
import polars as pl


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--execution-id", required=True)
    parser.add_argument("--realization", type=int, required=True)
    parser.add_argument("--iteration", type=int, required=True)
    parser.add_argument("--step-time", type=int, required=True)
    parser.add_argument("--api-url", default="http://localhost:8000")
    args = parser.parse_args()

    # Sleep to simulate a slower forward model
    time.sleep(0.5)

    # 1. Read field data
    # Orchestrator injects ParameterDataset as field_data_0.parquet
    field_file = Path("field_data_0.parquet")
    if not field_file.exists():
        print(f"Error: {field_file} not found")
        return

    df = pl.read_parquet(field_file)

    # 2. Simulate "physics"
    # Wells at (2,2) and (7,7)
    wells = {"W1": (2, 2), "W2": (7, 7)}

    results = []
    for w_name, (wx, wy) in wells.items():
        # Calculate base influence from all cells
        # We simplify: influence is PERM * exp(-dist/3)
        influence = (
            df.with_columns(
                [
                    (((pl.col("i") - wx) ** 2 + (pl.col("j") - wy) ** 2) ** 0.5).alias(
                        "dist",
                    ),
                ],
            )
            .with_columns(
                [(pl.col("PERM") * ((-pl.col("dist") / 3.0).exp())).alias("weighted")],
            )
            .select(pl.col("weighted").sum())
            .to_series()[0]
        )

        t = args.step_time
        val = float(influence * (1.0 + 0.1 * t))
        results.append(
            {
                "realization": args.realization,
                "source_step": f"field_model_{t}",
                "key": {"well": w_name, "time": str(t)},
                "value": val,
            },
        )

    # 3. Ingest results
    ingest_url = (
        f"{args.api_url}/experiments/{args.experiment_id}/executions/"
        f"{args.execution_id}/ensembles/{args.iteration}/ingest"
    )

    for payload in results:
        try:
            resp = httpx.post(ingest_url, json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            print(f"Failed to ingest {payload['key']}: {e}")
        except httpx.RequestError as e:
            print(f"Network error ingesting {payload['key']}: {e}")

    print(f"Successfully simulated and ingested W1, W2 for t={args.step_time}")


if __name__ == "__main__":
    main()
