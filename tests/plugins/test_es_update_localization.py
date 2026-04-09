import numpy as np
import polars as pl

from gert.experiments.models import GridMetadata, ParameterMetadata
from gert.plugins.es_update import ESUpdate
from gert.updates.spatial import SpatialToolkit


def test_es_update_with_spatial_grid() -> None:
    # 1. Setup Spatial Toolkit with a 10x10 Grid (100 parameters)
    toolkit = SpatialToolkit()
    grid = GridMetadata(id="surface_grid", shape=(10, 10))
    toolkit.register_grid(grid)

    # 2. Setup Parameter Metadata
    param_meta = [
        ParameterMetadata(
            name="surface_param",
            columns=["surface_param"],
            grid_id="surface_grid",
        ),
    ]

    # 3. Create initial parameters (ensemble size = 20)
    # The parameters are unrolled as a single List column 'surface_param' of length 100
    ensemble_size = 20
    np.random.seed(42)
    # create wide dataframe where each row is a realization, and 'surface_param' is a list of 100 floats
    params_data = [
        {
            "realization": r,
            "surface_param": np.random.normal(10, 2, size=100).tolist(),
        }
        for r in range(ensemble_size)
    ]
    parameters = pl.DataFrame(params_data)

    # 4. Create observations
    # Say we have 3 observations
    obs_data = [
        {"id": 0, "response": "y", "x": 2.0, "y": 2.0, "value": 15.0, "std_dev": 1.0},
        {"id": 1, "response": "y", "x": 5.0, "y": 5.0, "value": 20.0, "std_dev": 1.0},
        {"id": 2, "response": "y", "x": 8.0, "y": 8.0, "value": 10.0, "std_dev": 1.0},
    ]
    observations = pl.DataFrame(obs_data)

    # 5. Create simulated responses (Tidy)
    resp_data = [
        {
            "realization": r,
            "response": o["response"],
            "x": o["x"],
            "y": o["y"],
            "value": np.random.normal(float(str(o["value"])), 3),
        }
        for r in range(ensemble_size)
        for o in obs_data
    ]
    simulated_responses = pl.DataFrame(resp_data)

    # 6. Execute update with localization
    algo = ESUpdate()
    args = {
        "alpha": 1.0,
        "localization_length": 5.0,
        "taper_function": "gaspari_cohn",
    }

    updated_params = algo.perform_update(
        parameters=parameters,
        parameter_metadata=param_meta,
        simulated_responses=simulated_responses,
        observations=observations,
        toolkit=toolkit,
        algorithm_arguments=args,
    )

    # Check that updated params has same shape
    assert len(updated_params) == ensemble_size
    assert "surface_param" in updated_params.columns
    # Check that it's a list column with 100 items per row
    first_list = updated_params["surface_param"][0]
    assert len(first_list) == 100
