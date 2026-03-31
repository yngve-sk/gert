#!/usr/bin/env python3
from pathlib import Path

import numpy as np
import polars as pl


def main() -> None:
    num_realizations = 21  # 0 is truth, 1-20 are prior ensemble
    nx, ny = 10, 10

    rng = np.random.default_rng(seed=42)

    data = []
    for r in range(num_realizations):
        if r == 0:
            # Truth has a "channel"
            perm = np.full((nx, ny), 10.0)
            perm[4:6, :] = 100.0
        else:
            # Prior members are random
            perm = rng.lognormal(mean=2.5, sigma=0.5, size=(nx, ny))

        data.extend(
            [
                {
                    "realization": r,
                    "i": i,
                    "j": j,
                    "PERM": float(perm[i, j]),
                }
                for i in range(nx)
                for j in range(ny)
            ],
        )

    df = pl.DataFrame(data)

    # Truth is realization 0
    truth_df = df.filter(pl.col("realization") == 0).with_columns(
        pl.lit(0).alias("realization"),
    )

    # Prior is 1..20, but we want them to be 0..19
    prior_df = df.filter(pl.col("realization") > 0)
    prior_df = prior_df.with_columns((pl.col("realization") - 1).alias("realization"))

    prior_df.write_parquet("prior_field.parquet")
    truth_df.write_parquet("truth_field.parquet")
    print(f"Generated prior and truth fields in {Path.cwd()}")


if __name__ == "__main__":
    main()
