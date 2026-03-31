"""CLI Monitor for GERT experiments using Textual."""

import json
import time
import urllib.request
from collections import defaultdict
from datetime import datetime
from typing import Any, ClassVar
from urllib.error import URLError

from pydantic import BaseModel, ConfigDict, Field
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.widgets import Footer, Header, Label, ProgressBar, Static, Tree
from textual.widgets.tree import TreeNode


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
ICON_FM = "⚙"
ICON_RES = "Σ"
ICON_REAL = "●"
ICON_ITER = "◆"

# Status Prefixes
PREFIX_PENDING = "○"
PREFIX_RUNNING = "◐"
PREFIX_DONE = "[green]✓[/]"
PREFIX_FAIL = "[red]✗[/]"


type NodeData = tuple[int, int, str | None, str | None]


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
    """Textual application for GERT experiment monitoring."""

    api_url: str
    experiment_id: str
    execution_id: str
    expected_count: int | None
    num_iterations: int
    status_url: str
    responses_url: str | None

    _statuses: dict[tuple[int, int], RealizationState]
    _responses: dict[int, dict[int, list[ResponseItem]]]
    _iteration_nodes: dict[int, TreeNode[NodeData | None]]
    _realization_nodes: dict[tuple[int, int], TreeNode[NodeData | None]]
    _step_nodes: dict[tuple[int, int, str], TreeNode[NodeData | None]]
    _iteration_bar_widgets: dict[int, tuple[ProgressBar, Label]]
    _selected_item: NodeData | None
    _total_steps_in_config: int | None
    _num_fm_steps: int

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
        width: 32;
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
        exec_id: str = execution_id or ""
        self.execution_id = exec_id

        # To be populated via _fetch_metadata
        self.num_iterations = 0
        self.expected_count = 0
        self._num_fm_steps = 0

        if not self.execution_id:
            self.status_url = f"{api_url}/experiments/{experiment_id}/status"
        else:
            self.status_url = (
                f"{api_url}/experiments/{experiment_id}/executions/"
                f"{self.execution_id}/status"
            )
        self.responses_url = None

        self._statuses = {}
        self._responses = {}
        self._iteration_nodes = {}
        self._realization_nodes = {}
        self._step_nodes = {}
        self._iteration_bar_widgets = {}
        self._exiting = False
        self._selected_item = None
        self._total_steps_in_config = None
        self._num_fm_steps = 0

    def compose(self) -> ComposeResult:
        """Compose the application layout.

        Yields:
            Layout widgets.
        """
        yield Header()
        with Vertical(id="top-pane"):
            yield StateSummary("Waiting for data...", id="summary-container")
            with ProgressView(id="progress-container"):
                yield Horizontal(
                    Label("Ensemble", classes="iteration-label"),
                    Label("Progress Bar", classes="header-label-centered"),
                    Label(
                        f"{ICON_FM} Steps | {ICON_RES} Resps",
                        classes="iteration-counter",
                    ),
                    classes="header-row",
                )

        with Horizontal(id="bottom-pane"):
            yield NavigationTree(
                f"Experiment {self.experiment_id} "
                f"({'Latest' if not self.execution_id else self.execution_id})",
                id="tree-view",
            )
            yield ResponseViewer(
                "Select a realization or step to view details.",
                id="response-view",
            )
        yield Footer()

    def on_mount(self) -> None:
        """Set up the application on mount."""
        self.title = f"GERT Monitor - {self.experiment_id}"
        tree = self.query_one("#tree-view", NavigationTree)
        tree.root.expand()

        self.set_interval(1.0, self._update_response_viewer)
        self._fetch_metadata()
        self.poll_api()

    @work(exclusive=True, thread=True)
    def _fetch_metadata(self) -> None:
        """Fetch the experiment metadata to know the planned bounds."""
        url = f"{self.api_url}/experiments/{self.experiment_id}/metadata"
        try:
            req = urllib.request.Request(url)  # noqa: S310
            with urllib.request.urlopen(req, timeout=5) as response:  # noqa: S310
                if response.getcode() == 200:
                    meta = json.loads(response.read().decode("utf-8"))
                    self.num_iterations = meta["num_iterations"]
                    self.expected_count = meta["num_realizations"]
                    self._num_fm_steps = meta["num_fm_steps"]
        except URLError:
            pass

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

    def _check_if_all_realizations_are_done(self) -> bool:
        """Poll the status API. Returns True if all expected realizations are done."""
        try:
            req = urllib.request.Request(self.status_url)  # noqa: S310
            with urllib.request.urlopen(req, timeout=5) as response:  # noqa: S310
                if response.getcode() == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    self.call_from_thread(self.process_data, data)

                    if self.expected_count is not None:
                        total_expected = self.expected_count * self.num_iterations
                        if len(self._statuses) >= total_expected and all(
                            s.status in {"COMPLETED", "FAILED"}
                            for s in self._statuses.values()
                        ):
                            return True
        except URLError:
            pass
        return False

    def _poll_responses(self) -> None:
        """Poll the responses API for all discovered iterations."""
        # Poll for each iteration we know about.
        iterations = {it for it, _ in self._statuses}
        for it in sorted(iterations):
            url = (
                f"{self.api_url}/experiments/{self.experiment_id}"
                f"/executions/{self.execution_id}/ensembles/{it}/responses"
            )
            try:
                req = urllib.request.Request(url)  # noqa: S310
                with urllib.request.urlopen(req, timeout=5) as response:  # noqa: S310
                    if response.getcode() == 200:
                        data = json.loads(response.read().decode("utf-8"))
                        self.call_from_thread(self.process_responses, it, data)
            except URLError:
                pass

    @work(exclusive=True, thread=True)
    def poll_api(self) -> None:
        """Poll the API for status updates in a background thread."""
        while not self._exiting:
            should_exit = self._check_if_all_realizations_are_done()
            self._poll_responses()

            if should_exit:
                time.sleep(1)
                self._exiting = True
                self.call_from_thread(self.exit)
                break

            time.sleep(0.5)

    def process_data(self, data: list[dict[str, Any]]) -> None:
        """Process API data and update UI components on the main thread."""
        parsed_data = [RealizationState.model_validate(item) for item in data]
        state_counts: dict[str, int] = defaultdict(int)

        # Precompute num_fm_steps from data if _fetch_config hasn't finished
        if self._num_fm_steps == 0 and parsed_data:
            self._num_fm_steps = max(
                (len(item.steps) for item in parsed_data),
                default=0,
            )

        iter_counts = self._init_iter_counts(parsed_data)
        tree = self.query_one("#tree-view", NavigationTree)

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
        summary = self.query_one(StateSummary)
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

            # Simple label without progress bar: "✓ Iteration 0 (10/10)"
            label = f"{it_prefix} Iteration {it} ({counts.done}/{counts.total})"

            if it not in self._iteration_nodes:
                self._iteration_nodes[it] = tree.root.add(label, expand=True)
            else:
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
            # Temporary label, will be overwritten in the second pass of process_data
            self._iteration_nodes[it] = tree.root.add(
                f"{ICON_ITER} Iteration {it}",
                expand=True,
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
                data=(it, r_id, None, None),
                expand=False,
            )
        else:
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
                data=(it, r_id, step_name, None),
                expand=False,
            )
            self._step_nodes[it, r_id, step_name] = step_node
            # Add log nodes
            step_node.add_leaf(
                f"{ICON_LOG} STDOUT",
                data=(it, r_id, step_name, "stdout"),
            )
            step_node.add_leaf(
                f"{ICON_LOG} STDERR",
                data=(it, r_id, step_name, "stderr"),
            )
        else:
            self._step_nodes[it, r_id, step_name].set_label(step_label)

    def _update_progress_bars(self, iter_counts: dict[int, IterationCount]) -> None:
        progress_view = self.query_one(ProgressView)

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
            counter_text = f"{step_info} | {resp_info}"
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

    def process_responses(self, iteration: int, data: list[dict[str, Any]]) -> None:
        """Process response data and update the cached responses on the main thread."""
        parsed_data = [ResponseItem.model_validate(item) for item in data]
        iteration_responses: dict[int, list[ResponseItem]] = defaultdict(list)
        for item in parsed_data:
            if item.realization is not None:
                iteration_responses[item.realization].append(item)

        self._responses[iteration] = dict(iteration_responses)

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
        viewer = self.query_one("#response-view", ResponseViewer)
        if item is None:
            viewer.update_response("Select a realization or step to view details.")
            return

        it, r_id, step_name, log_type = item
        state = self._statuses.get((it, r_id))
        if not state:
            return

        if log_type:
            self._show_log_details(viewer, it, r_id, step_name or "unknown", log_type)
        elif step_name:
            self._show_step_details(viewer, it, r_id, step_name, state)
        else:
            self._show_realization_details(viewer, it, r_id)

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
    app = GertMonitorApp(
        api_url,
        experiment_id,
        execution_id,
    )
    app.run()
