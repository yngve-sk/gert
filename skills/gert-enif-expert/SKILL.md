---
name: gert-enif-expert
description: Expert knowledge for working on the Ensemble Information Filter (EnIF) plugin in GERT. Use this skill when debugging, implementing, or modifying the EnIF data assimilation math and its parameters.
---

# GERT EnIF Expert

This skill contains the mathematical rules and specific `polars` / `numpy` matrix manipulations required for the EnIF data assimilation plugin.

## Core References

When making mathematical updates or changing parameter schemas, use the `read_file` tool to consult the following repository documentation:

- **docs/developers/enif_implementation_4_ai.md**: Detailed breakdown of the EnIF algorithm's required data shapes, `polars` to `numpy` extraction steps, precision matrix building (with NetworkX graphs), and final dataframe reassembly rules.
- **docs/developers/update_algorithms.md**: The general contract for all update algorithms, explaining the role of the `UpdateAlgorithm` base class and the `SpatialToolkit`.

Use these references to ensure the complex tensor math remains compliant with both the scientific paper expectations and the strict GERT data contracts.
