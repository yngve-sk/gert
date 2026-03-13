# GERT (Generic Ensemble Reservoir Tool)

![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)
![License: GPLv3](https://img.shields.io/badge/License-GPLv3-green.svg)

**GERT** is a modern, API-first, and strictly domain-agnostic orchestration engine for ensemble-based modeling and history matching.

Designed as a clean-room, ground-up reimagining of legacy ensemble tools, GERT acts purely as a highly scalable execution loop. It completely decouples mathematical data assimilation algorithms and domain-specific simulators from the core orchestration engine, exposing its capabilities entirely through robust HTTP and WebSocket APIs.

---

## ⚡ Core Philosophy & Features

* 🌍 **Strictly Domain-Agnostic:** GERT possesses zero knowledge of specific forward models (i.e., reservoir engineering, fluid dynamics, or specific simulators). Parameters and responses are treated purely as generic 1D/2D/3D tensors or scalar values.
* 🚀 **API-Driven Data Ingestion (Push, Not Poll):** GERT abandons heavy file-system watchers. Forward models primarily push sparse data payloads directly to a high-throughput ingestion API, which seamlessly consolidates the data into columnar `.parquet` files via `polars`.
* 🔒 **Immutable Configurations:** Experiment configurations are treated as absolute, immutable artifacts. GERT enforces strict reproducibility by permanently embedding the exact prior Parameter Matrix used at initialization.
* 🧮 **Decoupled Mathematics:** GERT does not do math. It manages the orchestration loop and passes flattened, high-performance `parquet` matrices to your external mathematical libraries of choice (e.g., `iterative_ensemble_smoother`).
* 🖥️ **HPC Abstraction:** Whether you are running 10 local workers on your laptop or scheduling 10,000 jobs on a Slurm/LSF cluster, GERT abstracts the compute layer using `psij-python`.

## 🏗️ High-Level Architecture

GERT operates as a distributed system comprised of distinct, strictly bounded services:
1. **Experiment Server (FastAPI):** Exposes the `POST /experiments` boundaries, manages immutable state, and handles WebSocket event streaming for frontend observability.
2. **Storage Server (Polars/Parquet):** A dark-storage backend that queues incoming `.jsonl` payloads and incrementally upserts them into analytical Parquet datasets.
3. **Execution Runner (`psij-python`):** The orchestrator that creates isolated scratch directories, injects deterministic parameter matrices, and talks to the cluster scheduler.

*(For detailed module boundaries and design constraints, please read the [Architecture](docs/developers/architecture.md) and [Design Rules](docs/developers/design_rules.md) documents).*

## 🛠 AI-Assisted Development
```bash
aider --message-file docs/developers/repo_context.md --read docs/developers/*
```

GERT is developed using a **"Documentation as Prompts"** philosophy. To ensure the AI agent (Aider) adheres to the strict architectural boundaries and clean-room design, you must boot it with the project's full context.

### 1. Booting the Agent
To start a coding session, run the following command from the repository root. This loads the core directives and all developer-facing design documents into the agent's active memory:

### 2. Development Workflow (TDD)
The AI agent is instructed to follow a strict Test-Driven Development loop. Follow the roadmap in docs/developers/roadmap.md using these three steps:

Scaffold: "Based on PR X.X, scaffold the module signatures for gert.module_name."

Test: "Write hypothesis property tests for these signatures in tests/."

Implement: "Now, implement the logic to make the tests pass. Ensure ruff and mypy pass."

### 3. Quality Gates
GERT uses pre-commit to enforce architectural integrity. You do not need to run linters manually; they will run automatically on every git commit.
```bash
pre-commit run --all-files
```

## ⚖️ Lineage & Legal

GERT's conceptual architecture and decoupled design are heavily inspired by the operational workflows of the legacy **Ensemble based Reservoir Tool (ERT)**, originally developed by Equinor ASA. We respectfully acknowledge Equinor's massive contribution to the open-source community and the field of ensemble-based history matching.

**Intellectual Property Boundary:** GERT is a completely independent, clean-room redesign. It contains **ZERO** source code copied from the original Equinor ERT repository. It is distributed under the GNU General Public License v3.0 (GPLv3). Please see the `NOTICE.md` and `LICENSE` files for full details.
