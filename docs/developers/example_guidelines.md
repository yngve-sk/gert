# GERT Example Guidelines

When creating examples for the GERT repository, follow these principles:

* **Use relative paths within the example directory** - Reference files as `forward_model.py`, not `../../examples/simple/forward_model.py`
* **Give forward model steps descriptive, domain-specific names** - Use names like `reservoir_simulator`, `flow_model`, `simple_polynomial` instead of generic terms like `dummy_fm`
* **Implement forward models as direct executables** - Avoid wrapper Python scripts that just call other scripts; make the forward model itself the executable
* **Keep examples self-contained** - All dependencies and files should be within the example's directory
* **Use realistic naming conventions** - Names should reflect what the model actually simulates or demonstrates
* Example executables should not be added to `[project.scripts]` as they are demonstration code, not production tools.
