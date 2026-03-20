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
    2. A test that submits a dummy runmodel to the `JobSubmitter` via `psij-python` using a local execution backend to verify the workdirs are populated correctly.
* Do not use integration tests to verify mathematical accuracy; use unit/hypothesis tests for that.

## 5. Prefer snapshot tests for larger objects
If an object has more than 4 attributes, and you are testing a function f(x) -> [a, b, c, d, ...], prefer doing snapshot tests to assert that given one x, you get out a certain set of outputs. This is better than one assert-line per individual attribute.

## 6. Hypothesis and File System Tests
* **No Fixtures with `@given`:** Never use pytest fixtures with `@given` hypothesis tests. Fixtures are function-scoped and cause state pollution between Hypothesis examples.
* **Create Temp Directories Explicitly:** For hypothesis tests that need file system isolation, create temporary directories explicitly within the test using `tempfile.TemporaryDirectory()` as a context manager:

## 7. Don't do this:
* Asserting the length of a list if there is already an assertion on the items of a list.
* Prefer assert a == [] over assert len(a) == 0
* Avoid redundant comments, only keep a comment if it adds value. If it is an internal note of what's happening, remove it and rather make the code clear so it is understandable.
* If you expect an expression to execute without raising an error, it is OK to simply evaluate the expression. DO NOT do a try-except and set a boolean in the except, only to assert it thereafter.
* If you create new files, always use a fixture for changing to tmpdir
* Create tmpdirs explicitly in parametrized tests, don't use function-scoped fixtures.

## 8. Whole-Object Assertions
* **Assert Against Complete Expected Objects:** When testing functions that return complex objects, construct the complete expected object and assert equality, rather than checking individual fields.
* **Good:**
  ```python
  result = my_function(input_data)
  expected = SomeClass(field1=value1, field2=value2, field3=value3)
  assert result == expected
  ```
* **Bad:**
  ```python
  result = my_function(input_data)
  assert result.field1 == value1
  assert result.field2 == value2
  assert result.field3 == value3
  ```
* **Why:** Whole-object assertions are more concise, catch unexpected fields, and make it obvious what the complete expected output should be.

## 9. Mock Sparingly - Test Real Behavior
- **Prefer Real Execution:** For I/O, file operations, and tool execution, test real behavior over mocking when operations are fast (< 100ms).
- **Mock Only:** Slow external services (HTTP APIs, HPC clusters), non-deterministic sources (timestamps, random), or dangerous operations (file deletion).
- **Don't Mock:** File system operations, subprocess calls to local tools, or your own classes.
- **The "Executable Outputs" Rule:** For components that create files or execute commands, write at least one test verifying real outputs, not just mock calls.

## 10. Avoid Sleep - Use Deterministic Waiting
- **Never use `time.sleep()`:** Replace arbitrary sleep calls with deterministic waiting mechanisms using `asyncio.wait_for()`, polling with exponential backoff, or test fixtures that explicitly wait for conditions (e.g., file existence, API responses) before proceeding.
