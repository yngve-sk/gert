# Localized ERT Polynomial Example

This example demonstrates how to use the Ensemble Smoother (ES-MDA) data assimilation algorithm in GERT with distance-based localization enabled.

Instead of scalar lists, this configuration sets up a full 2D surface grid (`[10, 10]`) and a 3D sub-surface grid (`[10, 10, 5]`).

### Key Concepts:
1. **Out-of-Core Parameter Datasets:** Uses `.parquet` files for grid initialization instead of inline JSON lists, matching large-scale computational requirements.
2. **Spatial Grids:** Two logical grids (`surface_grid` and `deep_grid`) are defined in the `experiment.json`.
3. **Distance-Based Localization:** Uses the Gaspari-Cohn taper function mapped across an `[x, y]` spatial coordinate.

### Running the Example
```bash
python examples/ert_poly_localized/generate_experiment.py
gert run --experiment-file examples/ert_poly_localized/experiment.json --working-dir examples/ert_poly_localized/workdirs
```
