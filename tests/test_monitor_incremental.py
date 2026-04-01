import pytest

from gert.experiments.models import ObservationSummary, UpdateMetadata
from gert.monitor import GertMonitorApp, NodeData, RealizationState


@pytest.mark.asyncio
async def test_monitor_process_data() -> None:
    app = GertMonitorApp("http://localhost:8000", "test_exp", "exec_1")
    app.num_iterations = 2
    app.expected_count = 1

    async with app.run_test() as pilot:
        # Mock payload from /status
        payload = [
            {
                "realization_id": 0,
                "iteration": 0,
                "status": "COMPLETED",
                "steps": [
                    {
                        "name": "step1",
                        "status": "COMPLETED",
                        "start_time": "2024-01-01T10:00:00Z",
                        "end_time": "2024-01-01T10:05:00Z",
                    },
                ],
            },
        ]

        # Call process_data
        app.process_data([RealizationState.model_validate(p) for p in payload])
        await pilot.pause()

        # Verify node was added
        assert 0 in app._iteration_nodes
        assert (0, 0) in app._realization_nodes


@pytest.mark.asyncio
async def test_monitor_process_update_metadata() -> None:
    app = GertMonitorApp("http://localhost:8000", "test_exp", "exec_1")
    app.num_iterations = 2
    app.expected_count = 1

    async with app.run_test() as pilot:
        # Ensure iteration node exists first so update node can be attached properly
        app.process_data(
            [
                RealizationState.model_validate(
                    {
                        "realization_id": 0,
                        "iteration": 1,
                        "status": "RUNNING",
                        "steps": [],
                    },
                ),
            ],
        )

        payload = {
            "status": "COMPLETED",
            "algorithm_name": "enif_update",
            "configuration": {"alpha": 1.0},
            "metrics": {"misfit_bias": 0.5},
            "start_time": "2024-01-01T10:00:00Z",
            "end_time": "2024-01-01T10:05:00Z",
            "duration_seconds": 300.0,
        }

        app.process_update_metadata(1, UpdateMetadata.model_validate(payload))
        await pilot.pause()

        assert 1 in app._update_metadata_cache
        assert app._update_metadata_cache[1].algorithm_name == "enif_update"
        assert 1 in app._update_nodes


@pytest.mark.asyncio
async def test_monitor_process_observation_summary() -> None:
    app = GertMonitorApp("http://localhost:8000", "test_exp", "exec_1")
    app.num_iterations = 2
    app.expected_count = 1

    async with app.run_test() as pilot:
        # Add basic iteration node
        app.process_data(
            [
                RealizationState.model_validate(
                    {
                        "realization_id": 0,
                        "iteration": 0,
                        "status": "COMPLETED",
                        "steps": [],
                    },
                ),
            ],
        )

        # Call process_observation_summary
        summary = ObservationSummary.model_validate(
            {
                "average_absolute_residual": 10.0,
                "average_normalized_misfit": 0.543,
                "average_absolute_misfit": 1.0,
                "details": [],
            },
        )
        app.process_observation_summary(0, summary)
        await pilot.pause()

        assert 0 in app._observation_summaries
        assert app._observation_summaries[0].average_normalized_misfit == 0.543

        # Verify it gets correctly pushed to display logic via next process_data
        app.process_data(
            [
                RealizationState.model_validate(
                    {
                        "realization_id": 0,
                        "iteration": 0,
                        "status": "COMPLETED",
                        "steps": [],
                    },
                ),
            ],
        )
        await pilot.pause()

        # Test formatting in widget (Optional but good check)
        cnt = app._iteration_bar_widgets[0][1]
        assert "0.543" in str(cnt.render())


@pytest.mark.asyncio
async def test_monitor_tree_selection() -> None:
    app = GertMonitorApp("http://localhost:8000", "test_exp", "exec_1")
    app.num_iterations = 2
    app.expected_count = 1

    async with app.run_test() as pilot:
        app.process_data(
            [
                RealizationState.model_validate(
                    {
                        "realization_id": 0,
                        "iteration": 0,
                        "status": "COMPLETED",
                        "steps": [],
                    },
                ),
            ],
        )

        # Simulate selecting an iteration node
        app._selected_item = NodeData(node_type="iteration", iteration=0)
        app._update_response_viewer()

        # Simulate selecting a realization node
        app._selected_item = NodeData(
            node_type="realization",
            iteration=0,
            realization_id=0,
        )
        app._update_response_viewer()

        # Add update metadata and select update node
        app.process_data(
            [
                RealizationState.model_validate(
                    {
                        "realization_id": 0,
                        "iteration": 1,
                        "status": "PENDING",
                        "steps": [],
                    },
                ),
            ],
        )
        app.process_update_metadata(
            1,
            UpdateMetadata.model_validate(
                {
                    "status": "RUNNING",
                    "algorithm_name": "test_algo",
                },
            ),
        )
        app._selected_item = NodeData(node_type="update", iteration=1)
        app._update_response_viewer()
