# GERT Coding Rules & Standards

This document defines the strict coding standards, formatting rules, and quality gates for the GERT repository. All code must adhere to these rules. We rely heavily on automated tooling to enforce these standards, minimizing manual nitpicking during code reviews.

---

## 1. Automated Linting & Formatting (`ruff`)
GERT uses [`ruff`](https://docs.astral.sh/ruff/) as the absolute authority for both linting and formatting.

* **The Opt-Out Philosophy:** GERT configures `ruff` with **all rules enabled by default** (`select = ["ALL"]` in `pyproject.toml`).
* **Rule Exemptions:** We only ignore specific rules if they strictly conflict with each other (e.g., formatting compatibility rules like `ISC001`) or if they are objectively detrimental to the GERT architecture. Any ignored rule in `pyproject.toml` must be accompanied by an inline comment explaining *why* it is ignored.
* **Auto-formatting:** The `ruff format` command is used for all code formatting. It replaces `black` and `isort`. Code must be formatted before being committed.
* **No manual style debates:** If `ruff format` and `ruff check` pass, the style is considered correct.

## 2. Strict Type Hinting
GERT is a fully type-annotated codebase. We use modern Python 3.10+ type hinting syntax (e.g., `list[str] | None` instead of `Union[List[str], None]`).

* **Validation:** All code must pass strict type checking using `mypy --strict` (or `pyright` in strict mode).
* **No Implicit `Any`:** Avoid using `Any` unless interfacing with completely untyped external legacy libraries. If you must use `Any`, add a `# type: ignore` comment explaining why.
* **Signatures:** Every function and method signature must have fully annotated arguments and a defined return type. (e.g., `def do_something() -> None:`).

## 3. Pre-commit Hooks
All developers must install and use the `pre-commit` framework to ensure no malformed code enters the repository.

* Run `uv run pre-commit install` upon cloning the repository.
* The pre-commit pipeline will automatically run `ruff check --fix`, `ruff format`, `mypy`, and standard file checks (trailing whitespace, end-of-file fixers) on every commit.
* Commits that fail the pre-commit pipeline will be rejected by CI/CD.

## 4. Naming Conventions & Code Style
* **Variables & Functions:** `snake_case`
* **Classes & Exceptions:** `PascalCase`
* **Constants:** `UPPER_SNAKE_CASE` (Defined at the module level).
* **Private/Internal Members:** Prefix internal module functions, methods, or variables with a single underscore (e.g., `_internal_method()`). This explicitly signals to external clients (like Everest) not to use them.

## 5. Function Design & Abstraction
* **Avoid Single-Usage Functions:** Do not create standalone, module-level helper functions if they are only ever called from one place. Keep the logic where it belongs.
* **Nested Functions for Readability:** As an exception to the above, if a single function's execution flow becomes highly complex or difficult to read, creating a single-use *nested function* (a closure defined inside the parent function) is encouraged to give that block of logic a descriptive name and isolate its scope.
* **Pragmatic DRY (Don't Repeat Yourself):** While DRY is a good principle, do not over-abstract. If the repeated logic is trivial (e.g., a simple list comprehension, dictionary extraction, or basic arithmetic), prefer to keep it "WET" (Write Everything Twice) and inline. Creating a dedicated function for a simple one-liner hurts readability by forcing the reader to jump around the file.
* The JobSubmitter operates as a stateless adapter focused solely on translating execution commands and queue configurations to the scheduler backend - it deliberately ignores experiment-specific identifiers to maintain reusability across different orchestration contexts.

## 6. Import Conventions
* **No Relative Parent Imports:** The use of relative parent imports (`from .. import x` or `from ...module import y`) is strictly disallowed. Always use absolute imports for cross-module boundaries (e.g., `from gert.storage.api import x`).
* **Respect Private Boundaries:** You must almost never import a private member (prefixed with `_`) from *another* module.
* **Refactor, Don't Violate Privacy:** If you find that you absolutely must import a private function, class, or variable from another module to complete your task, **do not** leave it as a private import. Instead, refactor the source module to explicitly export that member and make it public (by removing the `_` prefix) so the architectural dependency is clear.

## 7. Docstrings
* Use the **Google Docstring Format**.
* All public modules, classes, and functions must have a descriptive docstring.
* Docstrings must describe the *intent* and *behavior* of the function, not just parrot the type hints.

## 8. Testing Standards
* **Framework:** All tests are written using `pytest`.
* **No Mocks in Production:** Mock data, dummy generators, and test orchestrators must **strictly** reside in the `tests/factories/` directory or `conftest.py`. Never embed test logic in the `src/gert/` source code.
* **Stateless Tests:** Tests must not rely on the global state or the order of execution. Each test must spin up and tear down its own necessary context.
* **Pragmatic Edge-Case Testing:** Do not write redundant tests for logically impossible edge cases. Because GERT enforces strict type hinting (`mypy`) and rigid data validation (`pydantic`), you do not need to write tests verifying what happens if a string is passed to an integer field. Rely on the boundary tools to do their jobs, and focus your tests on realistic execution paths and domain logic.
* **Asserting Failures:** When testing the "Fail Fast" design rule, use `pytest.raises` to explicitly verify that invalid user input triggers the correct, descriptive error message.

## 9. Architectural Compliance
Code must not only pass syntax and linting checks but also adhere to the structural boundaries defined in the repository context:
* Verify your module dependencies against `interfaces.md`.
* Ensure your logic adheres strictly to `design_rules.md` (e.g., maintaining domain agnosticism and immutability).
**Configuration Immutability Pattern:** Objects that require configuration should receive their configuration parameters during initialization and store them immutably, rather than accepting configuration as arguments to operational methods. This ensures clear ownership, prevents configuration drift, and makes the object's behavior predictable throughout its lifetime.

## 10. Design for Testability
All code must be written so that it is easily and quickly unit-testable. To achieve this, strictly follow these patterns:
* **Isolate I/O from Logic (Functional Core, Imperative Shell):** Functions that perform complex logic, math, or data transformations must not read from disk, make network calls, or fetch their own state. They should accept pure data structures (e.g., DataFrames, Pydantic models) as arguments and return new data structures.
* **Dependency Injection:** Do not hardcode or instantiate heavy services (like database clients or cluster schedulers) deep inside nested functions. Pass the initialized service (or its abstract interface) in as an argument. This allows the test suite to easily pass in a lightweight, in-memory mock.
* **Avoid Global State:** Do not use module-level mutable variables. State must be explicitly passed through function arguments.

## 11. Misc
* Always respect this: An exception must not use a string literal for its message, assign the literal to variable first.
* Don't write redundant comments. Prefer only commenting where necessary. Inline comments should always be there to explain the purpose of the line below. But if the purpose can be explained from code, leave it uncommented.
* Always specify return types, including None of __init__
* Don't use boolean positional arguments in function definitions, prefer doing a *, first, so kwarg usage is enforced
* Respect a maximum line length of 88, never create lines longer than this.
* Write at most 2 expressions in an assertion, respecting PT018.
* All code must pass pre-commit validation before submission.
