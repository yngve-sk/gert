import json
import pathlib

from numpy.random import Generator, default_rng


def generate_experiment() -> None:
    n_reals = 20
    rng: Generator = default_rng(42)

    # Initial guesses with large uncertainty to see convergence
    # Truth: A=0.5, B=1.0, C=3.0
    a_priors = rng.normal(loc=1.0, scale=1.0, size=n_reals)
    b_priors = rng.normal(loc=0.0, scale=2.0, size=n_reals)
    c_priors = rng.normal(loc=0.0, scale=5.0, size=n_reals)

    a_values = {str(i): float(val) for i, val in enumerate(a_priors)}
    b_values = {str(i): float(val) for i, val in enumerate(b_priors)}
    c_values = {str(i): float(val) for i, val in enumerate(c_priors)}

    # Observations from ERT poly example

    obs_data = [
        (0, 2.265648, 0.600000),
        (2, 7.466611, 1.400000),
        (4, 14.153351, 3.000000),
        (6, 24.843010, 5.400000),
        (8, 43.565715, 8.600000),
    ]

    observations = [
        {"key": {"response": "y", "x": str(x)}, "value": val, "std_dev": std}
        for x, val, std in obs_data
    ]

    # We do a few iterations to let the data assimilation update parameters
    updates = [
        {
            "name": f"step_{i}",
            "algorithm": "enif_update",
            "arguments": {
                "random_seed": i,
                "neighbor_propagation_order": 1,
            },
        }
        for i in range(1, 6)
    ]

    experiment = {
        "name": "ert-poly-example",
        "forward_model_steps": [
            {
                "name": "poly_eval",
                "executable": "poly_eval.py",
                "args": [
                    "--experiment-id",
                    "{experiment_id}",
                    "--execution-id",
                    "{execution_id}",
                    "--realization",
                    "{realization}",
                    "--iteration",
                    "{iteration}",
                ],
            },
        ],
        "updates": updates,
        "queue_config": {
            "backend": "local",
            "custom_attributes": {},
        },
        "parameter_matrix": {
            "metadata": {
                "A": {"source": "prior", "updatable": True},
                "B": {"source": "prior", "updatable": True},
                "C": {"source": "prior", "updatable": True},
            },
            "values": {
                "A": a_values,
                "B": b_values,
                "C": c_values,
            },
            "datasets": [],
        },
        "observations": observations,
    }

    with pathlib.Path("examples/ert_poly/experiment.json").open(
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(experiment, f, indent=2)
    print("Generated experiment.json")


if __name__ == "__main__":
    generate_experiment()
