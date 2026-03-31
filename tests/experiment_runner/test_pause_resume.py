import asyncio
import json
from pathlib import Path

import pytest

from gert.experiment_runner.experiment_orchestrator import ExperimentOrchestrator
from gert.experiments import ExecutionState
from gert.experiments.models import (
    ExecutableForwardModelStep,
    ExperimentConfig,
    ParameterMatrix,
    QueueConfig,
)


@pytest.fixture
def stoppable_config(tmp_path: Path) -> ExperimentConfig:
    # A single step that sleeps so we can interrupt it
    step = ExecutableForwardModelStep(
        name="sleepy",
        executable="/bin/sleep",
        args=["1"],
    )

    return ExperimentConfig(
        name="stoppable_exp",
        base_working_directory=tmp_path,
        storage_base=tmp_path / "permanent_storage",
        realization_workdirs_base=tmp_path / "workdirs",
        forward_model_steps=[step],
        queue_config=QueueConfig(backend="local"),
        parameter_matrix=ParameterMatrix(
            values={"p1": {0: 1.0, 1: 2.0}},  # 2 realizations
        ),
        observations=[],
        updates=[],
    )


@pytest.mark.asyncio
async def test_pause_and_resume_flow(
    stoppable_config: ExperimentConfig,
    tmp_path: Path,
) -> None:
    # 1. Start Orchestrator
    orchestrator = ExperimentOrchestrator(
        config=stoppable_config,
        experiment_id="exp-123",
    )

    # Actually use the real job submitter, it will submit local processes.
    task = asyncio.create_task(orchestrator.run_experiment())

    # Wait for the orchestrator to reach the loop and start jobs
    await asyncio.sleep(0.5)

    # Ensure it's running
    assert len(orchestrator._active_jobs[0]) == 2

    # Force Pause
    orchestrator.pause(force=True)

    # Wait for task to exit
    await asyncio.wait_for(task, timeout=2.0)

    # Verify state was saved
    state_file = (
        tmp_path
        / "permanent_storage"
        / stoppable_config.name
        / orchestrator._execution_id
        / "execution_state.json"
    )
    assert state_file.exists()

    # Read state
    state_json = state_file.read_text()

    data = json.loads(state_json)
    assert data["status"] == "PAUSED"

    # 2. Resume Orchestrator
    # To test resume, let's pretend realization 0 succeeded before the crash/pause
    state = ExecutionState.model_validate_json(state_json)
    state.completed_realizations.append(0)
    state.status = "RUNNING"

    # Recreate orchestrator with resume state
    orchestrator2 = ExperimentOrchestrator(
        config=stoppable_config,
        experiment_id="exp-123",
        resume_state=state,
    )

    assert orchestrator2._current_iteration == 0

    # Run it
    task2 = asyncio.create_task(orchestrator2.run_experiment())

    # Wait a bit
    await asyncio.sleep(0.5)

    # It should have skipped realization 0, and only submitted realization 1!
    # BUT wait, the previous test didn't write responses, so perform_update will fail if updates > 0.
    # We set updates=[] in stoppable_config, so it will just finish the iteration and exit.

    # Complete realization 1 manually for speed, or let it finish (sleep 1)
    await orchestrator2.record_realization_complete(0, 1, step_name="sleepy")

    await asyncio.wait_for(task2, timeout=5.0)

    # Did it run successfully?
    assert (
        len(orchestrator2._active_jobs[0]) == 1
    )  # Only one job should be active (realization 1)
