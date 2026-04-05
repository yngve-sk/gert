from gert.experiments.models import ObservationSummary
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
    assert (
        app.status_url
        == "http://dummy:8000/experiments/test_exp/executions/test_exec/status"
    )
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
        average_normalized_misfit=1.5,
        average_absolute_residual=2.5,
        average_absolute_misfit=3.5,
        details=[],
    )

    app.process_observation_summary(0, summary)

    assert 0 in app._observation_summaries
    assert app._observation_summaries[0].average_normalized_misfit == 1.5
