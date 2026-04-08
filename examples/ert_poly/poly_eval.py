#!/usr/bin/env python3
import argparse
import json
import logging
from pathlib import Path

from gert.plugins.forward_model_client import GertForwardModelClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate a polynomial A*x^2 + B*x + C",
    )
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
        param_file = Path("parameters.json")
        if param_file.exists():
            params = json.loads(param_file.read_text(encoding="utf-8"))
            a = float(params.get("A", 0.0))
            b = float(params.get("B", 0.0))
            c = float(params.get("C", 0.0))
        else:
            logger.warning("parameters.json not found, using defaults")
            a, b, c = 0.5, 1.0, 3.0

        logger.info(
            f"[Realization {args.realization}] Evaluating "
            f"A={a:.3f}, B={b:.3f}, C={c:.3f}",
        )

        # ERT poly example observations are for x in [0, 2, 4, 6, 8]
        # We evaluate the polynomial at these points and post the response
        for x in [0, 2, 4, 6, 8]:
            y = a * (x**2) + b * x + c

            client.post_response(
                key={"response": "y", "x": str(x)},
                value=y,
            )
            logger.info(f"  x={x}, y={y:.3f} posted.")


if __name__ == "__main__":
    main()
