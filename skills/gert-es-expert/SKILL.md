---
name: gert-es-expert
description: Expert knowledge for working on the Ensemble Smoother (ES-MDA) plugin in GERT. Use this skill when implementing or modifying the ES-MDA data assimilation algorithm.
---

# GERT ES Expert

This skill contains the specific guidelines and implementation strategies for the Ensemble Smoother (ES-MDA) data assimilation plugin.

## Core References

When modifying or implementing ES-MDA algorithms, use the `read_file` tool to consult the following repository documentation:

- **docs/developers/es_update_implementation_4_ai.md**: The blueprint for building the ES-MDA algorithm, covering localization, inflation factors, and the iterative update loop constraints.
- **docs/developers/update_algorithms.md**: The general contract for all update algorithms, explaining the role of the `UpdateAlgorithm` base class and the `SpatialToolkit`.
