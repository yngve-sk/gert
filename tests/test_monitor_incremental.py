import pytest

from gert.experiments.models import ObservationDetail, ObservationSummary
from gert.monitor import GertMonitorApp


def test_monitor_state_initialization() -> None:
    """Test that the monitor app initializes its internal state correctly."""
    app = GertMonitorApp(
        api_url="http://dummy:8000",
        experiment_id="test_exp",
        execution_id="test_exec",
    )
    assert app.api_url == "http://dummy:8000"
    assert app.experiment_id == "test_exp"
    assert app.execution_id == "test_exec"
    assert app._statuses == {}
    assert app._exiting is False


def test_monitor_process_observation_summary() -> None:
    """Test processing of observation summaries directly updates the state."""
    app = GertMonitorApp(
        api_url="http://dummy",
        experiment_id="test_exp",
        execution_id="test_exec",
    )

    summary = ObservationSummary(
        average_misfit=1.5,
        average_absolute_residual=2.5,
        average_absolute_misfit=3.5,
        details=[],
    )

    app.process_observation_summary(0, summary)

    assert 0 in app._observation_summaries
    assert app._observation_summaries[0].average_misfit == 1.5


@pytest.mark.asyncio
async def test_monitor_misfit_rendering() -> None:
    """Ensure the observation summary correctly updates the UI misfit label."""
    app = GertMonitorApp(
        api_url="http://dummy",
        experiment_id="test_exp",
        execution_id="test_exec",
    )

    # We fake config fetching to bypass network inside this isolated UI test.
    app.num_iterations = 2
    app.expected_count = 1
    app._num_fm_steps = 1

    async with app.run_test() as pilot:
        # Wait for the screen to mount
        await pilot.pause()

        # Inject a raw websocket event to populate statuses and trigger initial UI draw
        app._process_ws_events(
            [
                {
                    "iteration": 0,
                    "realization_id": 0,
                    "step_name": "poly",
                    "status": "COMPLETED",
                    "timestamp": "2026-01-01T00:00:00Z",
                },
            ],
        )
        await pilot.pause()

        # Verify it shows N/A initially
        counters = app.screen.query(".iteration-counter")
        counter_texts = [str(c.render()) for c in counters]
        assert any("N/A" in t for t in counter_texts), (
            f"Expected N/A in {counter_texts}"
        )

        # Inject summary
        summary = ObservationSummary(
            average_misfit=10.0,
            average_absolute_residual=2.0,
            average_absolute_misfit=5.0,
            details=[
                ObservationDetail(
                    response="test",
                    key={"x": "5.0"},
                    absolute_residual=2.0,
                    misfit=10.0,
                    absolute_misfit=5.0,
                ),
            ],
        )

        # This will trigger the missing self._refresh_ui() we just added
        app.process_observation_summary(0, summary)
        await pilot.pause()

        # Verify the number is rendered instead of N/A
        counters = app.screen.query(".iteration-counter")
        counter_texts = [str(c.render()) for c in counters]
        assert any("5.000" in t for t in counter_texts), (
            f"Expected 5.000 in {counter_texts}"
        )
