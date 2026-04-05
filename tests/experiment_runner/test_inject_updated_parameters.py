from pathlib import Path

import polars as pl

from gert.experiment_runner.experiment_orchestrator import ExperimentOrchestrator
from gert.experiments.models import (
    ExperimentConfig,
    FileReference,
    ParameterDataset,
    ParameterMatrix,
    QueueConfig,
)


def test_inject_parameters_overwrites_with_updated_dataframe(tmp_path: Path) -> None:
    # Setup prior dataset
    prior_path = tmp_path / "prior_field.parquet"
    pl.DataFrame(
        {
            "realization": [0, 0, 1, 1],
            "i": [0, 1, 0, 1],
            "j": [0, 0, 0, 0],
            "PERM": [10.0, 20.0, 30.0, 40.0],
        },
    ).write_parquet(prior_path)

    config = ExperimentConfig(
        name="test_exp",
        base_working_directory=tmp_path,
        forward_model_steps=[],
        queue_config=QueueConfig(backend="local"),
        observations=[],
        parameter_matrix=ParameterMatrix(
            datasets=[
                ParameterDataset(
                    reference=FileReference(
                        path="prior_field.parquet",
                        format="parquet",
                    ),
                    parameters=["PERM"],
                    index_columns=["i", "j"],
                ),
            ],
            values={},
        ),
    )

    orchestrator = ExperimentOrchestrator(
        config=config,
        experiment_id="test-exp",
        api_url="",
    )

    # The updated parameters dataframe (what perform_update returns and replace_values_from_df sets)
    updated_df = pl.DataFrame(
        {
            "realization": [0, 1],
            "PERM": [
                [99.0, 199.0],
                [299.0, 399.0],
            ],  # Lists representing the aggregated updated values
        },
    )

    # Simulate a ParameterMatrix after Iteration > 0
    updated_matrix = ParameterMatrix(
        metadata=config.parameter_matrix.metadata,
        values=config.parameter_matrix.values,
        datasets=config.parameter_matrix.datasets,
        dataframe=updated_df,
    )

    workdir = tmp_path / "workdir"
    workdir.mkdir()

    # Call _inject_parameters for realization 0
    orchestrator._inject_parameters(workdir, 0, updated_matrix)

    # Check the injected dataset
    injected_file = workdir / "field_data_0.parquet"
    assert injected_file.exists()

    injected_df = pl.read_parquet(injected_file)

    # It should only contain realization 0
    assert len(injected_df) == 2
    assert injected_df["realization"].to_list() == [0, 0]

    # The PERM values should be OVERWRITTEN by the updated_df values
    assert injected_df["PERM"].to_list() == [99.0, 199.0]
