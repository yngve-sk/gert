import asyncio
import contextlib
import json
import time
from pathlib import Path

import pytest

from gert.experiment_runner.experiment_orchestrator import ExperimentOrchestrator
from gert.experiments.models import (
    ExecutableForwardModelStep,
    ExperimentConfig,
    ParameterMatrix,
    QueueConfig,
)


@pytest.fixture
def stoppable_config(tmp_path: Path) -> ExperimentConfig:
    dummy_script = tmp_path / "dummy_sleep.sh"
    dummy_script.write_text("#!/bin/bash\nsleep $1\n")
    dummy_script.chmod(0o755)

    step = ExecutableForwardModelStep(
        name="sleepy",
        executable=str(dummy_script),
        args=["2"],
    )

    return ExperimentConfig(
        name="stoppable_exp",
        base_working_directory=tmp_path,
        storage_base=tmp_path / "permanent_storage",
        realization_workdirs_base=tmp_path / "workdirs",
        forward_model_steps=[step],
        queue_config=QueueConfig(backend="local"),
        parameter_matrix=ParameterMatrix(
            values={"p1": {0: 1.0, 1: 2.0, 2: 3.0}},
        ),
        observations=[],
        updates=[],
    )


@pytest.mark.asyncio
async def test_reconstruct_state_from_log(
    stoppable_config: ExperimentConfig,
    tmp_path: Path,
) -> None:
    """Test that the orchestrator correctly rebuilds its state from the event log."""
    execution_id = "test_resume_exec"
    log_dir = stoppable_config.storage_base / stoppable_config.name / execution_id
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "status_events.jsonl"

    events = [
        {
            "iteration": 0,
            "realization_id": 0,
            "status": "COMPLETED",
            "step_name": "sleepy",
            "timestamp": "2024-01-01T10:00:00Z",
        },
        {
            "iteration": 0,
            "realization_id": 0,
            "status": "COMPLETED",
            "timestamp": "2024-01-01T10:00:00Z",
        },
        {
            "iteration": 0,
            "realization_id": 1,
            "status": "FAILED",
            "timestamp": "2024-01-01T10:00:00Z",
        },
        {
            "iteration": 0,
            "realization_id": 2,
            "status": "ACTIVE",
            "timestamp": "2024-01-01T10:00:00Z",
        },
    ]

    with log_file.open("w") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    orchestrator = ExperimentOrchestrator(
        config=stoppable_config,
        experiment_id=stoppable_config.name,
        api_url="http://localhost:8080",
        execution_id=execution_id,
    )

    assert orchestrator._current_iteration == 0
    assert 0 in orchestrator._successful_realizations[0]
    assert 1 in orchestrator._failed_realizations[0]
    assert 2 not in orchestrator._successful_realizations[0]
    assert 2 not in orchestrator._failed_realizations[0]
    assert "sleepy" in orchestrator._successful_steps[0][0]


@pytest.mark.asyncio
async def test_hard_pause_cancels_jobs(
    stoppable_config: ExperimentConfig,
    tmp_path: Path,
) -> None:
    """Test that a hard pause immediately cancels running jobs."""
    step = stoppable_config.forward_model_steps[0]
    if isinstance(step, ExecutableForwardModelStep):
        step.args = ["10"]

    orchestrator = ExperimentOrchestrator(
        config=stoppable_config,
        experiment_id=stoppable_config.name,
        api_url="http://localhost:8080",
    )

    task = asyncio.create_task(orchestrator.run_experiment())

    await asyncio.sleep(0.5)

    assert orchestrator._active_jobs[0], "Jobs should be active"

    start_time = time.time()
    orchestrator.pause(force=True)

    with contextlib.suppress(Exception):
        await asyncio.wait_for(task, timeout=3.0)

    duration = time.time() - start_time
    assert duration < 2.0, (
        f"Hard pause took too long ({duration}s), jobs were not cancelled immediately."
    )


@pytest.mark.asyncio
async def test_soft_pause_waits_for_jobs(
    stoppable_config: ExperimentConfig,
    tmp_path: Path,
) -> None:
    """Test that a soft pause waits for running jobs to finish."""
    step = stoppable_config.forward_model_steps[0]
    if isinstance(step, ExecutableForwardModelStep):
        step.args = ["1"]

    orchestrator = ExperimentOrchestrator(
        config=stoppable_config,
        experiment_id=stoppable_config.name,
        api_url="http://localhost:8080",
    )

    task = asyncio.create_task(orchestrator.run_experiment())

    await asyncio.sleep(0.1)

    start_time = time.time()
    orchestrator.pause(force=False)

    with contextlib.suppress(Exception):
        await asyncio.wait_for(task, timeout=3.0)

    duration = time.time() - start_time
    assert duration > 0.8, (
        f"Soft pause returned too quickly ({duration}s), didn't wait for jobs."
    )
