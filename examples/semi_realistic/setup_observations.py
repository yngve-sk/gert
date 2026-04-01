#!/usr/bin/env python3
import json
from pathlib import Path

import polars as pl


def main() -> None:
    truth_file = Path("truth_field.parquet")
    if not truth_file.exists():
        print("Run generate_prior.py first")
        return

    df = pl.read_parquet(truth_file)

    wells = {"W1": (2, 2), "W2": (7, 7)}
    timesteps = range(1, 11)

    observations = []
    for w_name, (wx, wy) in wells.items():
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

        for t in timesteps:
            val = float(influence * (1.0 + 0.1 * t))
            observations.append(
                {
                    "key": {"response": "FOPR", "well": w_name, "time": str(t)},
                    "value": val,
                    "std_dev": val * 0.05,  # 5% relative error
                },
            )

    # Read and update experiment.json directly
    exp_file = Path("experiment.json")
    with exp_file.open("r", encoding="utf-8") as f:
        config = json.load(f)

    # Dynamically inject 10 forward model steps for our 10 timesteps
    forward_model_steps = [
        {
            "name": f"field_model_{t}",
            "executable": "./field_model.py",
            "args": [
                "--experiment-id",
                "{experiment_id}",
                "--execution-id",
                "{execution_id}",
                "--realization",
                "{realization}",
                "--iteration",
                "{iteration}",
                "--step-time",
                str(t),
            ],
        }
        for t in timesteps
    ]

    config["forward_model_steps"] = forward_model_steps
    config["observations"] = observations

    with exp_file.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

    with Path("observations.json").open("w", encoding="utf-8") as f:
        json.dump(observations, f, indent=2)

    print(
        f"Generated {len(observations)} observations from truth field "
        "and updated experiment.json.",
    )


if __name__ == "__main__":
    main()
