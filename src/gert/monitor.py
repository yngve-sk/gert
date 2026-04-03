"""CLI Monitor for GERT experiments using Textual."""

import io
import json
import time
import traceback
import urllib.request
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, ClassVar
from urllib.error import URLError

import polars as pl
from pydantic import BaseModel, ConfigDict, Field
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label, ProgressBar, Static, Tree
from textual.widgets.tree import TreeNode

from gert.experiments.models import ExperimentConfig, ObservationSummary, UpdateMetadata


class StepState(BaseModel):
    """State of an individual forward model step."""

    name: str
    status: str
    start_time: str | datetime | None = None
    end_time: str | datetime | None = None


class RealizationState(BaseModel):
    """State of a specific realization execution including its steps."""

    realization_id: int
    iteration: int
    status: str
    steps: list[StepState] = Field(default_factory=list)


class ResponseItem(BaseModel):
    """A single emitted response from a forward model."""

    model_config = ConfigDict(extra="allow")

    realization: int | None = None
    source_step: str | None = None
    value: Any | None = None
    type: str | None = None


class IterationCount(BaseModel):
    """Progress counting for an iteration."""

    total: int = 0
    done: int = 0
    total_steps: int = 0
    done_steps: int = 0
    total_responses: int = 0
    observation_summary: ObservationSummary | None = None


class ResponseViewer(Static):
    """Widget to view the last response of a selected realization or step details."""

    def update_response(self, text: str) -> None:
        """Update the displayed text."""
        self.update(text)


class StateSummary(Static):
    """Displays a summary of realization states."""

    def update_summary(self, states_count: dict[str, int]) -> None:
        """Update the summary string."""
        summary_parts = []
        for state, count in sorted(states_count.items()):
            summary_parts.append(f"{state}: {count}")
        self.update(
            " | ".join(summary_parts) if summary_parts else "Waiting for data...",
        )


# Icons for the TUI
ICON_LOG = "󰈙" if False else "⬚"  # Fallback for standard terminals
ICON_FM = "🌍"
ICON_RES = "🔥"
ICON_REAL = "🧱"
ICON_ITER = "🧱..🧱"

# Status Prefixes
PREFIX_PENDING = "○"
PREFIX_RUNNING = "◐"
PREFIX_DONE = "[green]✓[/]"
PREFIX_FAIL = "[red]✗[/]"


class ExecutionBrowserScreen(Screen[str]):
    """Screen to browse and select an execution."""

    BINDINGS: ClassVar[list[Any]] = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
    ]

    def __init__(self, api_url: str, experiment_id: str) -> None:
        super().__init__()
        self.api_url = api_url
        self.experiment_id = experiment_id

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label(
            f"Executions for experiment: [bold blue]{self.experiment_id}[/]",
            id="browser-title",
        )
        yield DataTable(id="execution-table")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Execution ID", "Status", "Last Update", "Iteration")
        table.cursor_type = "row"
        table.zebra_stripes = True
        self._fetch_executions()

    def action_refresh(self) -> None:
        self._fetch_executions()

    @work(exclusive=True, thread=True)
    def _fetch_executions(self) -> None:
        url = f"{self.api_url}/experiments/{self.experiment_id}/executions"
        try:
            req = urllib.request.Request(url)  # noqa: S310
            with urllib.request.urlopen(req, timeout=5) as response:  # noqa: S310
                if response.getcode() == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    # ExecutionState objects
                    self.app.call_from_thread(self._update_table, data)
        except (URLError, json.JSONDecodeError):
            pass

    def _update_table(self, executions: list[dict[str, Any]]) -> None:
        table = self.query_one(DataTable)
        table.clear()
        for exec_data in executions:
            table.add_row(
                exec_data["execution_id"],
                exec_data["status"],
                exec_data.get("last_modified", "N/A"),
                str(exec_data.get("current_iteration", 0)),
                key=exec_data["execution_id"],
            )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection to switch to monitor dashboard."""
        exec_id = str(event.row_key.value)
        self.dismiss(exec_id)


class MonitorDashboardScreen(Screen[None]):
    """Main dashboard screen for monitoring a specific execution."""

    BINDINGS: ClassVar[list[Any]] = [
        ("b", "browser", "Execution Browser"),
        ("e", "expand_all", "Expand/Collapse All"),
        ("p", "toggle_plotter", "Plotter"),
    ]

    def __init__(self, api_url: str, experiment_id: str, execution_id: str) -> None:
        super().__init__()
        self.api_url = api_url
        self.experiment_id = experiment_id
        self.execution_id = execution_id

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="top-pane"):
            yield StateSummary("Waiting for data...", id="summary-container")
            with ProgressView(id="progress-container"):
                yield Horizontal(
                    Label("Ensemble", classes="iteration-label"),
                    Label("Progress Bar", classes="header-label-centered"),
                    Label(
                        f"{ICON_FM} Steps | {ICON_RES} Resps | avg norm misfit",
                        classes="iteration-counter",
                    ),
                    classes="header-row",
                )

        with Horizontal(id="bottom-pane"):
            yield NavigationTree(
                f"Experiment {self.experiment_id} ({self.execution_id})",
                id="tree-view",
            )
            yield ResponseViewer(
                "Select a realization or step to view details.",
                id="response-view",
            )
        yield Footer()

    def action_browser(self) -> None:
        self.dismiss()

    def action_toggle_plotter(self) -> None:
        # This will need to be updated to use self.app.push_screen
        pass


class NodeData(BaseModel):
    """Data attached to each tree node for navigation details."""

    node_type: str  # "iteration", "update", "realization", "step", "log"
    iteration: int
    realization_id: int | None = None
    step_name: str | None = None
    log_type: str | None = None


class ProgressView(ScrollableContainer):
    """Displays progress bars for each iteration."""


class NavigationTree(Tree[NodeData | None]):
    """A tree that allows left/right arrow navigation without scrolling."""

    BINDINGS: ClassVar[list[Any]] = [
        ("left", "collapse_node", "Collapse"),
        ("right", "expand_node", "Expand"),
    ]

    def action_collapse_node(self) -> None:
        """Collapse the current node or move to parent."""
        if self.cursor_node:
            if self.cursor_node.is_expanded:
                self.cursor_node.collapse()
            elif self.cursor_node.parent:
                self.move_cursor(self.cursor_node.parent)

    def action_expand_node(self) -> None:
        """Expand the current node."""
        if self.cursor_node and not self.cursor_node.is_expanded:
            self.cursor_node.expand()


class GertMonitorApp(App[None]):
    CSS = """
    Screen {
        layout: vertical;
    }

    #top-pane {
        height: 40%;
        border-bottom: solid green;
    }

    #summary-container {
        height: 3;
        border-bottom: dashed gray;
        content-align: center middle;
    }

    #progress-container {
        height: 1fr;
    }

    .iteration-row {
        height: 1;
        layout: horizontal;
    }

    .iteration-label {
        width: 15;
        content-align: right middle;
        padding-right: 1;
    }

    .iteration-counter {
        width: 52;
        padding-left: 1;
        content-align: left middle;
    }

    .header-row {
        height: 1;
        layout: horizontal;
        text-style: bold;
        color: $accent;
    }

    .header-label-centered {
        width: 1fr;
        content-align: center middle;
    }

    ProgressBar {
        width: 1fr;
        padding: 0;
        margin: 0;
    }

    #bottom-pane {
        height: 60%;
        layout: horizontal;
    }

    #tree-view {
        width: 40%;
        border-right: solid green;
    }

    #response-view {
        width: 60%;
        padding: 1;
        overflow: scroll;
    }
    """

    BINDINGS: ClassVar[list[Any]] = [
        ("q", "quit", "Quit"),
        ("e", "expand_all", "Expand/Collapse All"),
        ("p", "toggle_plotter", "Plotter"),
    ]

    def __init__(
        self,
        api_url: str,
        experiment_id: str,
        execution_id: str | None = None,
    ) -> None:
        """Initialize the monitor app."""
        super().__init__()
        self.api_url = api_url
        self.experiment_id = experiment_id
        self.execution_id = execution_id or ""

        # To be populated via _fetch_config
        self.num_iterations = 0
        self.expected_count = 0
        self._num_fm_steps = 0
        self.num_observations = 0
        self.num_parameters = 0
        self.experiment_name = ""

        self._reset_state()

    def _reset_state(self) -> None:
        self._statuses = {}
        self._responses = {}
        self._iteration_nodes = {}
        self._update_nodes = {}
        self._update_metadata_cache = {}
        self._observation_summaries = {}
        self._realization_nodes = {}
        self._step_nodes = {}
        self._iteration_bar_widgets = {}
        self._exiting = False
        self._selected_item = None
        self._total_steps_in_config = None

        if self.execution_id:
            self.status_url = (
                f"{self.api_url}/experiments/{self.experiment_id}/executions/"
                f"{self.execution_id}/status"
            )
        else:
            self.status_url = ""

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Initializing...")
        yield Footer()

    def on_mount(self) -> None:
        self._fetch_config()
        # Push browser as the root screen
        self.push_screen(
            ExecutionBrowserScreen(self.api_url, self.experiment_id),
            callback=self._show_dashboard,
        )
        if self.execution_id:
            # If starting with a specific execution, push dashboard on top
            self.push_screen(
                MonitorDashboardScreen(
                    self.api_url,
                    self.experiment_id,
                    self.execution_id,
                ),
            )
            self.poll_api()

    def _show_browser(self) -> None:
        # Browser is usually pushed at mount or when popping
        pass

    def _show_dashboard(self, execution_id: str | None) -> None:
        if not execution_id:
            # Browser was closed without selection
            self.exit()
            return

        self.execution_id = execution_id
        self._reset_state()
        self.push_screen(
            MonitorDashboardScreen(self.api_url, self.experiment_id, execution_id),
        )
        self.poll_api()

    def stop_polling(self) -> None:
        self._exiting = True

    @work(exclusive=True, thread=True)
    def _fetch_config(self) -> None:
        """Fetch the experiment config to know the planned bounds."""
        url = f"{self.api_url}/experiments/{self.experiment_id}/config"
        try:
            req = urllib.request.Request(url)  # noqa: S310
            with urllib.request.urlopen(req, timeout=5) as response:  # noqa: S310
                if response.getcode() == 200:
                    config_json = response.read().decode("utf-8")
                    config = ExperimentConfig.model_validate_json(config_json)
                    self.experiment_name = config.name
                    self.num_observations = config.num_observations
                    self.num_parameters = config.num_parameters
                    self.num_iterations = config.num_iterations
                    self.expected_count = config.num_realizations
                    self._num_fm_steps = config.num_fm_steps
        except URLError:
            pass
        except Exception as e:  # noqa: BLE001
            # If config fails to parse, fallback to defaults so we can still display data
            self.num_iterations = 1
            self.expected_count = 0
            self._num_fm_steps = 0

    async def action_quit(self) -> None:
        """Handle the quit action and cleanup threads."""
        self._exiting = True
        self.exit()

    def action_expand_all(self) -> None:
        """Toggle expand/collapse all iterations and realizations."""
        any_collapsed = any(not n.is_expanded for n in self._iteration_nodes.values())
        if not any_collapsed:
            any_collapsed = any(
                not n.is_expanded for n in self._realization_nodes.values()
            )

        if any_collapsed:
            self._expand_all_nodes()
        else:
            self._collapse_all_nodes()

    def _expand_all_nodes(self) -> None:
        for node in self._iteration_nodes.values():
            node.expand()
        for node in self._realization_nodes.values():
            node.expand()

    def _collapse_all_nodes(self) -> None:
        for node in self._iteration_nodes.values():
            node.collapse()
        for node in self._realization_nodes.values():
            node.collapse()

    def on_unmount(self) -> None:
        """Cleanup any remaining threads on unmount."""
        self._exiting = True

    def _format_time(self, time_val: str | datetime | None) -> str:
        """Format a ISO timestamp into a human-readable string."""
        if not time_val:
            return "N/A"
        if isinstance(time_val, datetime):
            return time_val.strftime("%H:%M:%S")
        try:
            # Pydantic/FastAPI sends ISO format
            dt = datetime.fromisoformat(time_val)
            return dt.strftime("%H:%M:%S")  # Just time for brevity in one-liner
        except (ValueError, TypeError):
            return str(time_val)

    def _get_status_emoji(self, status: str) -> str:
        """Get an emoji representing the status."""
        return {
            "PENDING": PREFIX_PENDING,
            "QUEUED": PREFIX_PENDING,
            "RUNNING": PREFIX_RUNNING,
            "ACTIVE": PREFIX_RUNNING,
            "COMPLETED": PREFIX_DONE,
            "FAILED": PREFIX_FAIL,
            "CANCELED": PREFIX_FAIL,
        }.get(status, "❓")

    def _get_step_summary_line(
        self,
        it: int,
        r_id: int,
        step_name: str,
        step: StepState | None,
    ) -> str:
        """Create a nice one-liner summary for a step."""
        st = step.status if step else "UNKNOWN"
        emoji = self._get_status_emoji(st)
        start = self._format_time(step.start_time) if step else "N/A"
        end = self._format_time(step.end_time) if step else "N/A"

        return (
            f"{ICON_FM} [bold blue]{step_name}[/] (It {it}, R {r_id}) | "
            f"{emoji} {st} | 🕒 {start} -> {end}"
        )

    def _check_if_all_realizations_are_done(self, logger) -> bool:
        """Poll the status API. Returns True if all expected realizations are done, or if the execution itself is done/failed."""
        if not self.status_url:
            logger.warning("status_url is empty!")
            return False

        terminal_execution = False
        state_url = (
            f"{self.api_url}/experiments/{self.experiment_id}"
            f"/executions/{self.execution_id}/state"
        )
        try:
            req_state = urllib.request.Request(state_url)  # noqa: S310
            with urllib.request.urlopen(req_state, timeout=5) as response_state:  # noqa: S310
                if response_state.getcode() == 200:
                    state_data = json.loads(response_state.read().decode("utf-8"))
                    exec_status = state_data.get("status")
                    if exec_status in {"COMPLETED", "FAILED", "PAUSED", "PAUSING"}:
                        logger.info(f"Execution reached terminal state: {exec_status}")
                        terminal_execution = True
        except URLError as e:
            logger.warning(f"URLError fetching execution state: {e}")
        except Exception as e:
            logger.warning(f"Exception fetching execution state: {e}")
        
        # Always update realizations for UI, even if terminal, to show the final state
        logger.info(f"Requesting status from {self.status_url}")
        try:
            req = urllib.request.Request(self.status_url)  # noqa: S310
            with urllib.request.urlopen(req, timeout=5) as response:  # noqa: S310
                logger.info(f"Got response code {response.getcode()}")
                if response.getcode() == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    logger.info(f"Received {len(data)} realization states")
                    parsed_data = [
                        RealizationState.model_validate(item) for item in data
                    ]
                    self.call_from_thread(self.process_data, parsed_data)

                    if terminal_execution:
                        return True

                    if (
                        self.expected_count is not None
                        and self.expected_count > 0
                        and self.num_iterations > 0
                    ):
                        total_expected = self.expected_count * self.num_iterations
                        if len(self._statuses) >= total_expected and all(
                            s.status in {"COMPLETED", "FAILED"}
                            for s in self._statuses.values()
                        ):
                            return True
        except URLError as e:
            logger.error(f"URLError fetching status: {e}")
        except Exception as e:
            logger.error(f"Exception fetching status: {e}", exc_info=True)
            
        return terminal_execution

    def _poll_responses(self, logger) -> None:
        """Poll the responses API for all discovered iterations."""
        # Poll for each iteration we know about.
        iterations = sorted({it for it, _ in self._statuses})
        if not iterations:
            logger.info("No iterations discovered to poll responses for.")
            return

        for it in iterations:
            self._poll_iteration_responses(it, logger)
            self._poll_extra_iteration_info(it, logger)

    def _poll_extra_iteration_info(self, it: int, logger) -> None:
        """Poll for observation summary and update metadata for an iteration."""
        # Poll for observation summary
        summary_url = (
            f"{self.api_url}/experiments/{self.experiment_id}"
            f"/executions/{self.execution_id}/ensembles/{it}/observation_summary"
        )
        try:
            summary_req = urllib.request.Request(summary_url)  # noqa: S310
            with urllib.request.urlopen(summary_req, timeout=5) as summary_resp:  # noqa: S310
                if summary_resp.getcode() == 200:
                    summary_data = json.loads(summary_resp.read().decode("utf-8"))
                    if summary_data is not None:
                        parsed_summary = ObservationSummary.model_validate(
                            summary_data,
                        )
                        self.call_from_thread(
                            self.process_observation_summary,
                            it,
                            parsed_summary,
                        )
        except URLError:
            pass

        # Poll for update metadata if iteration > 0
        if it > 0:
            meta_url = (
                f"{self.api_url}/experiments/{self.experiment_id}"
                f"/executions/{self.execution_id}/ensembles/{it}/update/metadata"
            )
            try:
                meta_req = urllib.request.Request(meta_url)  # noqa: S310
                with urllib.request.urlopen(meta_req, timeout=5) as meta_resp:  # noqa: S310
                    if meta_resp.getcode() == 200:
                        meta_data = json.loads(meta_resp.read().decode("utf-8"))
                        parsed_meta = UpdateMetadata.model_validate(meta_data)
                        self.call_from_thread(
                            self.process_update_metadata,
                            it,
                            parsed_meta,
                        )
            except URLError:
                pass
        
    def _poll_iteration_responses(self, it: int, logger) -> None:
        url = (
            f"{self.api_url}/experiments/{self.experiment_id}"
            f"/executions/{self.execution_id}/ensembles/{it}/responses"
        )
        try:
            req = urllib.request.Request(url)  # noqa: S310
            with urllib.request.urlopen(req, timeout=5) as response:  # noqa: S310
                if response.getcode() == 200:
                    data_bytes = response.read()
                    if data_bytes:
                        df = pl.read_parquet(io.BytesIO(data_bytes))
                        data = df.to_dicts()
                        parsed_data = [
                            ResponseItem.model_validate(item) for item in data
                        ]
                        self.call_from_thread(self.process_responses, it, parsed_data)
        except URLError:
            pass
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Failed to poll responses: {e}")
    @work(exclusive=True, thread=True)
    def poll_api(self) -> None:
        """Poll the API for status updates in a background thread."""
        counter = 0
        import logging
        logger = logging.getLogger("GertMonitor")
        
        done_cycles = 0
        while not self._exiting:
            logger.info(f"Polling API... counter={counter}")
            is_done = self._check_if_all_realizations_are_done(logger)
            logger.info(f"is_done={is_done}")

            self._poll_responses(logger)

            counter += 1

            if is_done:
                done_cycles += 1
                # Wait a few cycles to ensure we pick up the final asynchronously written .parquet files
                if done_cycles > 3:
                    logger.info("Experiment done, exiting poll loop.")
                    break

            time.sleep(1.0)

    def process_data(self, parsed_data: list[RealizationState]) -> None:
        """Process API data and update UI components on the main thread."""
        state_counts: dict[str, int] = defaultdict(int)

        # Precompute num_fm_steps from data if _fetch_config hasn't finished
        if self._num_fm_steps == 0 and parsed_data:
            self._num_fm_steps = max(
                (len(item.steps) for item in parsed_data),
                default=0,
            )

        iter_counts = self._init_iter_counts(parsed_data)
        try:
            tree = self.screen.query_one("#tree-view", NavigationTree)
        except Exception:  # noqa: BLE001
            return

        # First pass: update all realizations and aggregate counts
        for item in parsed_data:
            r_id = item.realization_id
            it = item.iteration
            st = item.status
            steps = item.steps

            if it not in iter_counts:
                continue

            self._statuses[it, r_id] = item
            state_counts[st] += 1

            if st in {"COMPLETED", "FAILED"}:
                iter_counts[it].done += 1

            for step in steps:
                if step.status in {"COMPLETED", "FAILED"}:
                    iter_counts[it].done_steps += 1

            iter_counts[it].total_responses += len(
                self._responses.get(it, {}).get(r_id, []),
            )
            self._update_realization_node(tree, it, r_id, st, steps)

        self._update_iteration_labels(tree, iter_counts)
        try:
            summary = self.screen.query_one(StateSummary)
        except Exception:  # noqa: BLE001
            return
        summary.update_summary(state_counts)
        self._update_progress_bars(iter_counts)

    def _init_iter_counts(
        self,
        data: list[RealizationState],
    ) -> dict[int, IterationCount]:
        """Pre-initialize counts with planned totals."""

        iter_counts: dict[int, IterationCount] = {}
        for i in range(self.num_iterations):
            planned_r = self.expected_count or 0
            if not planned_r and data:
                # Fallback discovery
                planned_r = len(
                    {item.realization_id for item in data if item.iteration == i},
                )
            iter_counts[i] = IterationCount(
                total=planned_r,
                done=0,
                total_steps=planned_r * self._num_fm_steps,
                done_steps=0,
                total_responses=0,
                observation_summary=self._observation_summaries.get(i),
            )
        return iter_counts

    def _update_iteration_labels(
        self,
        tree: NavigationTree,
        iter_counts: dict[int, IterationCount],
    ) -> None:
        """Second pass: update iteration nodes with correct final prefixes."""
        for it, counts in iter_counts.items():
            is_it_done = counts.done == counts.total and counts.total > 0
            it_prefix = PREFIX_DONE if is_it_done else ICON_ITER

            if it > 0 and it not in self._update_nodes:
                self._update_nodes[it] = tree.root.add(
                    f"🧮✨ Update (Iter {it - 1} → {it})",
                    expand=False,
                    data=NodeData(node_type="update", iteration=it),
                )

            # Simple label without progress bar: "✓ Iteration 0 (10/10)"
            label = f"{it_prefix} Iteration {it} ({counts.done}/{counts.total})"

            if it not in self._iteration_nodes:
                self._iteration_nodes[it] = tree.root.add(
                    label,
                    expand=True,
                    data=NodeData(node_type="iteration", iteration=it),
                )
            elif self._iteration_nodes[it].label != label:
                self._iteration_nodes[it].set_label(label)

    def _update_realization_node(
        self,
        tree: NavigationTree,
        it: int,
        r_id: int,
        st: str,
        steps: list[StepState],
    ) -> None:
        """Update a single realization node and its steps."""
        if it not in self._iteration_nodes:
            if it > 0 and it not in self._update_nodes:
                self._update_nodes[it] = tree.root.add(
                    f"🧮✨ Update (Iter {it - 1} → {it})",
                    expand=False,
                    data=NodeData(node_type="update", iteration=it),
                )
            # Temporary label, will be overwritten in the second pass of process_data
            self._iteration_nodes[it] = tree.root.add(
                f"{ICON_ITER} Iteration {it}",
                expand=True,
                data=NodeData(node_type="iteration", iteration=it),
            )

        iter_node = self._iteration_nodes[it]

        # Determine realization label and prefix
        status_emoji = self._get_status_emoji(st)

        # Step progress: (completed_steps / total_planned)
        done_steps = sum(1 for s in steps if s.status in {"COMPLETED", "FAILED"})
        total_s = self._num_fm_steps if self._num_fm_steps > 0 else len(steps)

        label = f"{status_emoji} Real {r_id} ({done_steps}/{total_s})"

        # Determine current running step for the label suffix
        current_step = next((s for s in steps if s.status == "RUNNING"), None)
        if current_step:
            label += f" - {current_step.name}"

        if (it, r_id) not in self._realization_nodes:
            self._realization_nodes[it, r_id] = iter_node.add(
                label,
                data=NodeData(
                    node_type="realization",
                    iteration=it,
                    realization_id=r_id,
                ),
                expand=False,
            )
        elif self._realization_nodes[it, r_id].label != label:
            self._realization_nodes[it, r_id].set_label(label)

        real_node = self._realization_nodes[it, r_id]
        for step in reversed(steps):
            self._update_step_node(real_node, it, r_id, step)

    def _update_step_node(
        self,
        real_node: TreeNode[NodeData | None],
        it: int,
        r_id: int,
        step: StepState,
    ) -> None:
        step_name = step.name
        step_status = step.status
        status_emoji = self._get_status_emoji(step_status)
        step_label = f"{status_emoji} {step_name}"

        if (it, r_id, step_name) not in self._step_nodes:
            step_node = real_node.add(
                step_label,
                data=NodeData(
                    node_type="step",
                    iteration=it,
                    realization_id=r_id,
                    step_name=step_name,
                ),
                expand=False,
            )
            self._step_nodes[it, r_id, step_name] = step_node
            # Add log nodes
            step_node.add_leaf(
                f"{ICON_LOG} STDOUT",
                data=NodeData(
                    node_type="log",
                    iteration=it,
                    realization_id=r_id,
                    step_name=step_name,
                    log_type="stdout",
                ),
            )
            step_node.add_leaf(
                f"{ICON_LOG} STDERR",
                data=NodeData(
                    node_type="log",
                    iteration=it,
                    realization_id=r_id,
                    step_name=step_name,
                    log_type="stderr",
                ),
            )
        elif self._step_nodes[it, r_id, step_name].label != step_label:
            self._step_nodes[it, r_id, step_name].set_label(step_label)

    def _update_progress_bars(self, iter_counts: dict[int, IterationCount]) -> None:
        try:
            progress_view = self.screen.query_one(ProgressView)
        except Exception:  # noqa: BLE001
            return

        # Aggregate totals across all iterations
        total_done = sum(c.done for c in iter_counts.values())
        total_r = sum(c.total for c in iter_counts.values())
        total_done_steps = sum(c.done_steps for c in iter_counts.values())
        total_planned_steps = sum(c.total_steps for c in iter_counts.values())
        total_responses = sum(c.total_responses for c in iter_counts.values())

        # We append a virtual iteration -1 for the "TOTAL" row
        display_counts = dict(iter_counts)
        display_counts[-1] = IterationCount(
            total=total_r,
            done=total_done,
            total_steps=total_planned_steps,
            done_steps=total_done_steps,
            total_responses=total_responses,
        )

        # Calculate padding needed for step counts
        # Max steps across all displayed rows
        max_step_val = max(total_planned_steps, 1)
        step_width = len(str(max_step_val))

        for it, counts in sorted(display_counts.items()):
            # Update Top View Progress Rows
            # Counter shows: Steps | Responses
            done_s = str(counts.done_steps).rjust(step_width)
            total_s = str(counts.total_steps).rjust(step_width)
            step_info = f"{ICON_FM} {done_s}/{total_s}"

            resp_info = f"{ICON_RES} {str(counts.total_responses).rjust(4)}"

            misfit_val = (
                counts.observation_summary.average_normalized_misfit
                if counts.observation_summary
                else None
            )
            misfit_str = f"{misfit_val:.3f}" if misfit_val is not None else "N/A"
            misfit_info = f"Δ {misfit_str.rjust(6)}"

            counter_text = f"{step_info} | {resp_info} | {misfit_info}"
            if it not in self._iteration_bar_widgets:
                pb = ProgressBar(total=max(1, counts.total), show_eta=False)
                cnt = Label(counter_text, classes="iteration-counter")
                self._iteration_bar_widgets[it] = (pb, cnt)

                label_text = f"Iteration {it}" if it >= 0 else "TOTAL"
                row = Horizontal(
                    Label(label_text, classes="iteration-label"),
                    pb,
                    cnt,
                    classes="iteration-row",
                )
                progress_view.mount(row)
            else:
                pb, cnt = self._iteration_bar_widgets[it]
                pb.total = max(1, counts.total)
                pb.progress = counts.done
                cnt.update(counter_text)

    def process_responses(
        self,
        iteration: int,
        parsed_data: list[ResponseItem],
    ) -> None:
        """Process response data and update the cached responses on the main thread."""
        iteration_responses: dict[int, list[ResponseItem]] = defaultdict(list)
        for item in parsed_data:
            if item.realization is not None:
                iteration_responses[item.realization].append(item)

        self._responses[iteration] = dict(iteration_responses)

    def process_observation_summary(
        self,
        iteration: int,
        parsed_summary: ObservationSummary,
    ) -> None:
        """Process observation summary data."""
        if not parsed_summary:
            return
        self._observation_summaries[iteration] = parsed_summary

    def process_update_metadata(
        self,
        iteration: int,
        parsed_meta: UpdateMetadata,
    ) -> None:
        """Process mathematical update metadata."""
        self._update_metadata_cache[iteration] = parsed_meta

        if iteration in self._update_nodes:
            node = self._update_nodes[iteration]
            emoji = self._get_status_emoji(parsed_meta.status)
            node.set_label(
                f"{emoji} 🧮✨ Update (Iter {iteration - 1} → {iteration}) "
                f"- {parsed_meta.algorithm_name}",
            )

    def on_tree_node_highlighted(
        self,
        event: Tree.NodeHighlighted[NodeData | None],
    ) -> None:
        """Handle tree node highlight to show detail data."""
        if event.node.data is not None:
            self._selected_item = event.node.data
        else:
            self._selected_item = None
        self._update_response_viewer()

    def on_tree_node_selected(
        self,
        event: Tree.NodeSelected[NodeData | None],
    ) -> None:
        """Handle tree node selection to show detail data."""
        if event.node.data is not None:
            self._selected_item = event.node.data
        else:
            self._selected_item = None
        self._update_response_viewer()

    def _update_response_viewer(self) -> None:
        """Update the response viewer for the selected realization or step."""
        item = self._selected_item
        try:
            viewer = self.screen.query_one("#response-view", ResponseViewer)
        except Exception:  # noqa: BLE001
            return
        if item is None:
            self._show_experiment_details(viewer)
            return

        it = item.iteration
        r_id = item.realization_id
        step_name = item.step_name
        log_type = item.log_type

        if item.node_type == "update":
            self._show_update_details(viewer, it)
            return

        if item.node_type == "iteration":
            self._show_iteration_details(viewer, it)
            return

        if r_id is None:
            return

        state = self._statuses.get((it, r_id))
        if not state:
            return

        if item.node_type == "log" and log_type:
            self._show_log_details(viewer, it, r_id, step_name or "unknown", log_type)
        elif item.node_type == "step" and step_name:
            self._show_step_details(viewer, it, r_id, step_name, state)
        elif item.node_type == "realization":
            self._show_realization_details(viewer, it, r_id)

    def _parse_time(self, time_val: str | datetime) -> datetime:
        if isinstance(time_val, datetime):
            return time_val
        return datetime.fromisoformat(time_val)

    def _get_times_for_nodes(
        self,
        states: list[RealizationState],
    ) -> tuple[datetime | None, datetime | None]:
        start = None
        end = None
        for state in states:
            for step in state.steps:
                if step.start_time:
                    try:
                        dt = self._parse_time(step.start_time)
                        if not start or dt < start:
                            start = dt
                    except ValueError:
                        pass
                if step.end_time:
                    try:
                        dt = self._parse_time(step.end_time)
                        if not end or dt > end:
                            end = dt
                    except ValueError:
                        pass
        return start, end

    def _show_experiment_details(self, viewer: ResponseViewer) -> None:
        """Show the root dashboard for the experiment."""
        start_time, end_time = self._get_times_for_nodes(list(self._statuses.values()))

        elapsed = "N/A"
        if start_time:
            now = datetime.now(tz=UTC) if end_time is None else end_time
            elapsed_td = now - start_time
            elapsed = str(elapsed_td).split(".")[0]

        total_expected = (self.expected_count or 0) * (self.num_iterations or 1)
        overall_status = self._determine_overall_status(
            list(self._statuses.values()),
            total_expected,
        )

        emoji = self._get_status_emoji(overall_status)

        current_iter = max([it for it, _ in self._statuses] + [0])
        total_iters = self.num_iterations

        exp_name = getattr(self, "experiment_name", self.experiment_id)
        num_obs = getattr(self, "num_observations", 0)
        num_params = getattr(self, "num_parameters", 0)

        total_responses = sum(
            len(resps)
            for iter_resps in self._responses.values()
            for resps in iter_resps.values()
        )

        start_str = start_time.strftime("%Y-%m-%d %H:%M:%S") if start_time else "N/A"
        content = [
            f"🧫 [bold blue]{exp_name}[/] (ID: [cyan]{self.execution_id}[/])",
            f"State: {emoji} {overall_status} | 📅 {start_str} | 🕒 {elapsed}",
            f"Progress: Iteration {current_iter} / {max(1, total_iters - 1)}",
            "",
            (
                f"👥 Realizations: {self.expected_count} | 🔄 Iters: {total_iters} | "
                f"{ICON_FM} Steps/Real: {self._num_fm_steps}"
            ),
            f"💧 Parameters: {num_params} | 🎯 Observations: {num_obs}",
            f"🔥 Total Responses Received: {total_responses}",
        ]
        viewer.update_response("\n".join(content))

    def _determine_overall_status(
        self,
        states: list[RealizationState],
        expected_count: int,
    ) -> str:
        all_completed = True
        any_failed = False
        any_running = False

        for state in states:
            if state.status == "FAILED":
                any_failed = True
            elif state.status in {"RUNNING", "ACTIVE"}:
                any_running = True
            elif state.status not in {"COMPLETED", "FAILED"}:
                all_completed = False

        if any_failed:
            return "FAILED"
        if any_running:
            return "RUNNING"
        if all_completed and len(states) == expected_count:
            return "COMPLETED"
        return "PENDING"

    def _show_iteration_details(self, viewer: ResponseViewer, iteration: int) -> None:
        """Show summary statistics for a specific iteration."""
        states = [s for (it, _), s in self._statuses.items() if it == iteration]
        start_time, end_time = self._get_times_for_nodes(states)

        elapsed = "N/A"
        if start_time:
            now = datetime.now(tz=UTC) if end_time is None else end_time
            elapsed_td = now - start_time
            elapsed = str(elapsed_td).split(".")[0]

        done_steps = sum(
            1
            for state in states
            for step in state.steps
            if step.status in {"COMPLETED", "FAILED"}
        )
        total_planned_steps = (self.expected_count or 0) * self._num_fm_steps

        overall_status = self._determine_overall_status(
            states,
            self.expected_count or 0,
        )

        emoji = self._get_status_emoji(overall_status)

        responses = self._responses.get(iteration, {})
        total_responses = sum(len(resps) for resps in responses.values())

        content = [
            f"{ICON_ITER} [bold]Iteration {iteration} Summary[/]",
            f"State: {emoji} {overall_status} | 🕒 {elapsed}",
            (
                f"{ICON_FM} Steps: {done_steps} / {total_planned_steps} | "
                f"🔥 Responses Received: {total_responses}"
            ),
        ]

        obs_summary = self._observation_summaries.get(iteration)
        if obs_summary:
            n_misfit = obs_summary.average_normalized_misfit
            a_resid = obs_summary.average_absolute_residual
            content.append(
                f"🎯 Avg Misfit: {n_misfit:.4f} | 📉 Avg Residual: {a_resid:.4f}",
            )
        else:
            content.append("🎯 Avg Misfit: Calc... | 📉 Avg Residual: Calc...")

        viewer.update_response("\n".join(content))

    def _show_update_details(self, viewer: ResponseViewer, iteration: int) -> None:
        """Show mathematical update metadata."""
        meta = self._update_metadata_cache.get(iteration)
        if not meta:
            viewer.update_response("Update metadata not yet available.")
            return

        emoji = self._get_status_emoji(meta.status)
        content = [
            f"🧮✨ [bold]Mathematical Update (Iter {iteration - 1} → {iteration})[/]",
            f"Algorithm: [bold blue]{meta.algorithm_name}[/]",
            f"Status: {emoji} {meta.status}",
        ]

        start = self._format_time(meta.start_time)
        end = self._format_time(meta.end_time)
        content.append(f"🕒 {start} -> {end}")
        if meta.duration_seconds:
            content.append(f"Duration: {meta.duration_seconds:.2f}s")
        if meta.error:
            content.append(f"\n[red]Error: {meta.error}[/]")

        if meta.configuration:
            content.extend(["", "[bold underline]Configuration:[/]", ""])
            content.extend(json.dumps(meta.configuration, indent=2).split("\n"))

        if meta.metrics:
            content.extend(["", "[bold underline]Metrics:[/]", ""])
            for k, v in meta.metrics.items():
                if isinstance(v, float):
                    content.append(f"  [cyan]{k}[/]: {v:.6f}")
                else:
                    content.append(f"  [cyan]{k}[/]: {v}")

        viewer.update_response("\n".join(content))

    def _show_log_details(
        self,
        viewer: ResponseViewer,
        it: int,
        r_id: int,
        step_name: str,
        log_type: str,
    ) -> None:
        state = self._statuses.get((it, r_id))
        step = (
            next((s for s in state.steps if s.name == step_name), None)
            if state
            else None
        )

        content = [
            self._get_step_summary_line(it, r_id, step_name, step),
            f"--- [bold]{log_type.upper()}[/] ---",
            "",
        ]

        log_url = (
            f"{self.api_url}/experiments/{self.experiment_id}/executions/"
            f"{self.execution_id}/ensembles/{it}/realizations/{r_id}/steps/"
            f"{step_name}/logs"
        )
        try:
            req = urllib.request.Request(log_url)  # noqa: S310
            with urllib.request.urlopen(req, timeout=2) as response:  # noqa: S310
                if response.getcode() == 200:
                    log_data = json.loads(response.read().decode("utf-8"))
                    content.append(log_data.get(log_type, "(Empty)"))
        except (URLError, json.JSONDecodeError, TimeoutError, ConnectionError):
            content.append("[red](Logs not yet available or failed to fetch)[/]")

        viewer.update_response("\n".join(content))

    def _show_step_details(
        self,
        viewer: ResponseViewer,
        it: int,
        r_id: int,
        step_name: str,
        state: RealizationState,
    ) -> None:
        step = next(
            (s for s in state.steps if s.name == step_name),
            None,
        )
        content = [
            self._get_step_summary_line(it, r_id, step_name, step),
            "",
        ]

        self._append_step_logs(content, it, r_id, step_name)
        viewer.update_response("\n".join(content))

    def _append_step_logs(
        self,
        content: list[str],
        it: int,
        r_id: int,
        step_name: str,
    ) -> None:
        log_url = (
            f"{self.api_url}/experiments/{self.experiment_id}/executions/"
            f"{self.execution_id}/ensembles/{it}/realizations/{r_id}/steps/"
            f"{step_name}/logs"
        )
        try:
            req = urllib.request.Request(log_url)  # noqa: S310
            with urllib.request.urlopen(req, timeout=2) as response:  # noqa: S310
                if response.getcode() == 200:
                    log_data = json.loads(response.read().decode("utf-8"))
                    content.extend(
                        [
                            "--- [bold]STDOUT[/] ---",
                            log_data.get("stdout", "(Empty)"),
                            "",
                            "--- [bold]STDERR[/] ---",
                            log_data.get("stderr", "(Empty)"),
                        ],
                    )
        except (URLError, json.JSONDecodeError, TimeoutError, ConnectionError):
            content.append("[red](Logs not yet available or failed to fetch)[/]")

    def _show_realization_details(
        self,
        viewer: ResponseViewer,
        it: int,
        r_id: int,
    ) -> None:
        responses = self._responses.get(it, {}).get(r_id, [])
        last_value = None
        key_fields = {}
        if responses:
            # Use only the last one for brevity
            last_resp = responses[-1]
            known_fields = {"realization", "source_step", "value", "type"}
            last_resp_dict = last_resp.model_dump()
            key_fields = {
                k: v
                for k, v in last_resp_dict.items()
                if k not in known_fields and v is not None
            }
            last_value = str(last_resp.value)

        st = self._statuses[it, r_id].status
        emoji = self._get_status_emoji(st)

        content = [
            f"{ICON_REAL} [bold]Realization {r_id}[/] (It {it})",
            f"Status: {emoji} {st}",
            f"Responses Emitted: [bold]{len(responses)}[/]",
            "",
            "[bold underline]Last Response:[/]",
        ]
        if responses:
            for k, v in key_fields.items():
                content.append(f"  [cyan]{k}[/]: {v}")
            content.append(f"  [yellow]Value[/]: {last_value}")
        else:
            content.append("  (None)")

        viewer.update_response("\n".join(content))


def start_monitor(
    api_url: str,
    experiment_id: str,
    execution_id: str | None = None,
) -> None:
    """Entry point for the monitor CLI command."""
    import logging
    logging.basicConfig(
        filename="monitor_debug.log",
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    logging.info(f"Starting monitor for API={api_url} Exp={experiment_id} Exec={execution_id}")

    app = GertMonitorApp(
        api_url,
        experiment_id,
        execution_id,
    )
    try:
        app.run()
    except Exception as e:
        import sys
        print(f"Exception during monitor run: {e}", file=sys.stderr)
        traceback.print_exc()
        raise
