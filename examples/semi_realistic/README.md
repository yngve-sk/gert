# Semi-Realistic Field Example

This example demonstrates GERT's capability to handle field-based parameters (2D/3D grids) and evaluate data assimilation algorithms.

## Features
- **Field Parameters**: Uses a 10x10 2D grid for permeability (`PERM`).
- **ParameterDataset**: Shows how to use out-of-core Parquet files for field data.
- **Trend-based Physics**: The forward model calculates production based on spatial permeability distribution.
- **Data Assimilation**: Includes 3 update iterations using `enif_update`.
- **Observations**: Multi-well, multi-timestep observations with assigned uncertainty.

## Setup
The example data is pre-generated, but can be recreated using:
```bash
python examples/semi_realistic/generate_prior.py
python examples/semi_realistic/setup_observations.py
```

## Running
```bash
# Start server
python -m gert server

# Run experiment
python -m gert run examples/semi_realistic/experiment.json --monitor
```
