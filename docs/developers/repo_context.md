# GERT (Generic Ensemble Reservoir Tool) - Repository Context

## Project Overview
Welcome to the GERT repository. GERT is a modern, API-first, and strictly **domain-agnostic** redesign of the legacy ERT (Ensemble based Reservoir Tool).

GERT acts purely as a scalable execution and orchestration engine for ensemble-based modeling. It decouples mathematical updates (data assimilation) and domain-specific simulators from the core orchestration loop.

---

## ⚠️ CRITICAL CONTEXT REQUIREMENT FOR AI AGENTS ⚠️
You are strictly forbidden from generating code based on your general training data for ERT. You MUST read and adhere to the architectural rules defined in the `docs/developers/` folder before taking any action.

**STOP AND VERIFY:** If you do not currently have the text of the following files loaded into your active context, you must halt and ask the user to attach them before writing any code:

1. **`architecture.md`**: The high-level system topology (Separation of Sampling, Data Ingestion, Execution).
2. **`design_rules.md`**: The 11 absolute architectural constraints governing the codebase.
3. **`interfaces.md`**: The definitive guide to module organization. Use this to determine *where* code belongs.
4. **`coding_rules.md`**: Strict formatting (`ruff`), type hinting (`mypy`), import conventions, and the rules for testable design.
5. **`test_strategy.md`**: The testing philosophy utilizing `hypothesis` for property-based testing and `pytest.raises` for fail-fast boundaries.
6. **`roadmap.md`**: The micro-stepped PR development plan. You must execute work strictly according to the current PR phase.
7. **`legacy_behavior.md`**: An archive of specific technical debts and tightly-coupled behaviors from legacy ERT that are strictly forbidden.

---

## ⚠️ Core Directives for All Contributors
When writing, refactoring, or suggesting code for this repository, you **MUST** adhere to the following constraints:

1. **Strict Domain Agnosticism:** Never introduce reservoir-specific nomenclature (e.g., `SummaryConfig`, `ECLIPSE`, `RFT`, `GenData`) into the core `gert.*` modules. Parameters and Responses are generic tensors, scalars, or JSON schemas.
2. **Immutability:** Experiment configurations are immutable artifacts. Never write code that updates the original configuration with posterior results.
3. **No Legacy Quirks:** Do not replicate ERT's legacy behaviors (e.g., silent file backups, implicit LOG10 variables, interleaved text arrays).
4. **Push, Not Poll:** Do not write file-system watchers. Data ingestion relies on forward models pushing sparse data to an HTTP/gRPC API.

---

## Tech Stack & Conventions
When generating code, use the following libraries and patterns:
* **Language:** Modern Python (3.10+). Strict type hinting is mandatory.
* **Data Models:** Use `pydantic` for all structured data models.
* **High-Performance Data:** Use `polars` for the incremental consolidation of `.jsonl` into columnar `.parquet` files.
* **Job Scheduling:** Use `psij-python` for all cluster interactions.
* **API/Web:** Use `FastAPI`.
* **Testing:** Use `pytest` and `hypothesis`. Never embed mock data directly in production code.

---

## 🔄 TDD Workflow (Mandatory)
When asked to implement a new feature or micro-step, you must strictly follow this iterative workflow to ensure the codebase remains in a working, testable state:
1. **Scaffold:** Generate the empty module files, class definitions, and function signatures with full type hints and docstrings. Leave the implementation empty.
2. **Test:** Generate the `pytest` test file for that specific scaffolding.
3. **Iterate:** Generate the actual implementation code to make the tests pass.

**Do not generate massive blocks of untested implementation logic in a single response. Always leave the build green.**
