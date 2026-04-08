---
name: gert-architect
description: Provides the comprehensive architectural vision, coding standards, design rules, and system boundaries for the GERT repository. Use when implementing new core features or fundamentally refactoring the system.
---

# GERT Architect

This skill provides deep contextual knowledge of GERT's core design philosophies, API contracts, and testing strategies.

## When to Consult the References

When making substantial changes, always use the `read_file` tool to read the specific detailed documents below (located in the repository's `docs/developers/` folder) to ensure your implementation aligns with the overarching repository goals:

- **docs/developers/coding_rules.md**: Strict `ruff` and `mypy` standards, naming conventions, and docstring rules.
- **docs/developers/design_rules.md**: The 14 non-negotiable architectural constraints (e.g., Domain Agnosticism, Separation of Prior from Execution, Fail Fast).
- **docs/developers/architecture.md**: The high-level map of Orchestrator vs. Math vs. Storage.
- **docs/developers/interfaces.md**: Deep dive into the specific API endpoints and JSON line protocols connecting the decoupled components.
- **docs/developers/legacy_behavior.md**: Context on how the system previously worked and why it was removed to prevent regressions.
- **docs/developers/test_strategy.md**: Guidelines for writing robust, isolated tests without relying on global state.
- **docs/developers/service_discovery.md**: How the disparate components locate each other via file drops.
- **docs/developers/robustification.md**: Guidelines on building resilient fault-tolerant orchestration.
- **docs/developers/repo_context.md**: High-level purpose of the repository.
- **docs/developers/roadmap.md**: Future directions to keep in mind so current implementations don't block upcoming features.

Always adhere to these guidelines to ensure consistency and prevent architectural drift.
