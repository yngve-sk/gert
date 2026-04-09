import json
import pathlib

import numpy as np
import polars as pl


def generate_experiment() -> None:
    n_reals = 20

    # 2D surface parameter grid (10x10) -> 100 features
    surface_rows = []
    deep_rows = []

    rng = np.random.default_rng()

    for r in range(n_reals):
        surface_grid = rng.normal(loc=10.0, scale=2.0, size=(10, 10))
        surface_rows.extend(
            [
                {
                    "realization": r,
                    "x": float(x),
                    "y": float(y),
                    "surface_param": float(surface_grid[x, y]),
                }
                for x in range(10)
                for y in range(10)
            ],
        )

        deep_grid = rng.normal(loc=50.0, scale=5.0, size=(10, 10, 5))
        deep_rows.extend(
            [
                {
                    "realization": r,
                    "x": float(x),
                    "y": float(y),
                    "z": float(z),
                    "deep_param": float(deep_grid[x, y, z]),
                }
                for x in range(10)
                for y in range(10)
                for z in range(5)
            ],
        )

    # Save to out-of-core Parquet datasets
    pl.DataFrame(surface_rows).write_parquet("surface_param.parquet")
    pl.DataFrame(deep_rows).write_parquet("deep_param.parquet")

    with pathlib.Path("experiment.json").open(encoding="utf-8") as f:
        data = json.load(f)

    # Clear the inline dicts since they only accept scalars
    data["parameter_matrix"]["values"] = {}

    data["parameter_matrix"]["datasets"] = [
        {
            "reference": {
                "path": "surface_param.parquet",
                "format": "parquet",
            },
            "parameters": ["surface_param"],
            "index_columns": ["x", "y"],
        },
        {
            "reference": {
                "path": "deep_param.parquet",
                "format": "parquet",
            },
            "parameters": ["deep_param"],
            "index_columns": ["x", "y", "z"],
        },
    ]

    with pathlib.Path("experiment.json").open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


if __name__ == "__main__":
    generate_experiment()
