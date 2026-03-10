# GERT Testing Strategy

GERT strictly follows a testing philosophy optimized for mathematical robustness, high execution speed, and minimal maintenance overhead.

## 1. Property-Based Testing (`hypothesis`)
For core domain logic, mathematical updates, matrix assembly, and parameter generation, GERT utilizes property-based testing via the [`hypothesis`](https://hypothesis.readthedocs.io/) library.
* **Why:** Instead of writing 10 individual unit tests with hardcoded "magic numbers" for a physical calculation, we define the properties of the data (e.g., "Standard deviations must be floats > 0.0", "Tensors must be 2D"). `hypothesis` will generate hundreds of valid permutations, including extreme real-world physical values, and verify that the system behaves correctly across the entire domain space.
* **Rule:** If a function performs numerical transformations, joining, or mathematical assimilation, write a `hypothesis` test for it.

## 2. Testing the "Fail Fast" Boundary
Because GERT relies on strict input validation (Rule 11) and `pydantic` models, we do not test impossible language edge cases (like passing a string to an integer addition). 
* **Negative Testing:** We *do* test that invalid domain logic is caught at the outermost boundary. Use `pytest.raises` to assert that providing mathematically impossible configurations (e.g., an observation with `std_dev = -1.5`) immediately triggers a clear, descriptive validation error before execution begins. All pytest.raises blocks must also catch a specific exception message, not just the type, i.e., use regex match.

## 3. Fast, Pure Unit Tests (The Bulk)
The vast majority of the test suite must run in milliseconds. 
* Because code is designed with **Dependency Injection** and **I/O Isolation**, you can unit test the `ExperimentOrchestrator`'s state machine without actually submitting jobs to an HPC cluster.
* Unit tests assert that given specific, valid inputs, the function under test returns the exact expected outputs or triggers the correct callbacks.

## 4. Minimal Integration Tests
Integration tests (tests that touch the disk, boot a FastAPI server, or spin up a background Polars worker) are slow and brittle. They must be kept to an absolute minimum.
* **The Goal:** Integration tests in GERT are only used to verify the "Glue" between major components.
* **Examples of valid integration tests:**
    1. A test that blasts 100 sparse JSON payloads to the API and verifies that the `ConsolidationWorker` successfully writes a correct `.parquet` file to disk.
    2. A test that submits a dummy runmodel to the `JobSubmitter` via `psij-python` using a local execution backend to verify the runpath is populated correctly.
* Do not use integration tests to verify mathematical accuracy; use unit/hypothesis tests for that.