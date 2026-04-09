#!/usr/bin/env python3
import argparse

import polars as pl

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
        source_step="poly_eval",
    )

    with client.run():
        surface_df = pl.read_parquet("field_data_0.parquet")
        center_val = surface_df.filter((pl.col("x") == 5.0) & (pl.col("y") == 5.0))[
            "surface_param"
        ][0]

        client.post_response(
            key={"response": "y", "x": 5.0, "y": 5.0},
            value=float(center_val * 1.5),
        )


if __name__ == "__main__":
    main()
