"""CLI Monitor for GERT experiments using Textual."""

import json
import time
import urllib.request
from collections import defaultdict
from typing import Any, ClassVar
from urllib.error import URLError

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.widgets import Footer, Header, Label, ProgressBar, Static, Tree
from textual.widgets.tree import TreeNode


class ResponseViewer(Static):
    """Widget to view the last response of a selected realization."""

    def update_response(self, text: str) -> None:
        self.update(text)


class StateSummary(Static):
    """Displays a summary of realization states."""

    def update_summary(self, states_count: dict[str, int]) -> None:
        summary_parts = []
        for state, count in sorted(states_count.items()):
            summary_parts.append(f"{state}: {count}")
        self.update(
            " | ".join(summary_parts) if summary_parts else "Waiting for data...",
        )


class ProgressView(ScrollableContainer):
    """Displays progress bars for each iteration."""


class NavigationTree(Tree[tuple[int, int] | None]):
    """A tree that allows left/right arrow navigation without scrolling."""

    BINDINGS: ClassVar[list[Any]] = [
        ("left", "collapse_node", "Collapse"),
        ("right", "expand_node", "Expand"),
    ]

    def action_collapse_node(self) -> None:
        if self.cursor_node:
            if self.cursor_node.is_expanded:
                self.cursor_node.collapse()
            elif self.cursor_node.parent:
                self.move_cursor(self.cursor_node.parent)

    def action_expand_node(self) -> None:
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

    _statuses: dict[tuple[int, int], dict[str, Any]]
    _responses: dict[tuple[int, int], list[dict[str, Any]]]
    _iteration_nodes: dict[int, TreeNode[tuple[int, int] | None]]
    _realization_nodes: dict[tuple[int, int], TreeNode[tuple[int, int] | None]]
    _iteration_progress: dict[int, ProgressBar]
    _selected_item: tuple[int, int] | None

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
    }
    """

    BINDINGS: ClassVar[list[Any]] = [
        ("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        api_url: str,
        experiment_id: str,
        execution_id: str | None = None,
        expected_count: int | None = None,
        num_iterations: int = 1,
    ) -> None:
        super().__init__()
        self.api_url = api_url
        self.experiment_id = experiment_id
        exec_id: str = execution_id or ""
        self.execution_id = exec_id
        self.expected_count = expected_count
        self.num_iterations = num_iterations

        if self.execution_id:
            self.status_url = (
                f"{api_url}/experiments/{experiment_id}"
                f"/executions/{self.execution_id}/status"
            )
            # We poll all iterations' responses in _poll_responses
            # so this initial URL is mostly a placeholder/base.
            self.responses_url = (
                f"{api_url}/experiments/{experiment_id}/executions/{self.execution_id}"
                f"/ensembles/0/responses"
            )
        else:
            self.status_url = f"{api_url}/experiments/{experiment_id}/status"
            self.responses_url = None

        self._statuses = {}
        self._responses = defaultdict(list)
        self._iteration_nodes = {}
        self._realization_nodes = {}
        self._iteration_progress = {}
        self._exiting = False
        self._selected_item = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="top-pane"):
            yield StateSummary("Waiting for data...", id="summary-container")
            yield ProgressView(id="progress-container")

        with Horizontal(id="bottom-pane"):
            yield NavigationTree(
                f"Experiment {self.experiment_id} "
                f"({'Latest' if not self.execution_id else self.execution_id})",
                id="tree-view",
            )
            yield ResponseViewer(
                "Select a realization to view its last response.",
                id="response-view",
            )
        yield Footer()

    def on_mount(self) -> None:
        self.title = f"GERT Monitor - {self.experiment_id}"
        tree = self.query_one("#tree-view", NavigationTree)
        tree.root.expand()

        self.set_interval(1.0, self._update_response_viewer)
        self.poll_api()

    async def action_quit(self) -> None:
        """Handle the quit action and cleanup threads."""
        self._exiting = True
        self.exit()

    def on_unmount(self) -> None:
        """Cleanup any remaining threads on unmount."""
        self._exiting = True

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
                            s["status"] in {"COMPLETED", "FAILED"}
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
        state_counts: dict[str, int] = defaultdict(int)
        iter_counts: dict[int, dict[str, int]] = defaultdict(
            lambda: {"total": 0, "done": 0},
        )

        tree = self.query_one("#tree-view", NavigationTree)

        for item in data:
            r_id = item["realization_id"]
            it = item["iteration"]
            st = item["status"]

            self._statuses[it, r_id] = item
            state_counts[st] += 1

            iter_counts[it]["total"] += 1
            if st in {"COMPLETED", "FAILED"}:
                iter_counts[it]["done"] += 1

            if it not in self._iteration_nodes:
                self._iteration_nodes[it] = tree.root.add(
                    f"Iteration {it}",
                    expand=True,
                )

            iter_node = self._iteration_nodes[it]

            label = f"Realization {r_id} [{st}]"
            if (it, r_id) not in self._realization_nodes:
                self._realization_nodes[it, r_id] = iter_node.add_leaf(
                    label,
                    data=(it, r_id),
                )
            else:
                self._realization_nodes[it, r_id].set_label(label)

        summary = self.query_one(StateSummary)
        summary.update_summary(state_counts)

        progress_view = self.query_one(ProgressView)
        for it, counts in iter_counts.items():
            pct = 0
            if counts["total"] > 0:
                pct = int(100 * counts["done"] / counts["total"])

            bar_len = 10
            filled = int(bar_len * pct / 100)
            bar = "█" * filled + "░" * (bar_len - filled)

            if it in self._iteration_nodes:
                self._iteration_nodes[it].set_label(f"Iteration {it} [{bar}] {pct}%")

            if it not in self._iteration_progress:
                pb = ProgressBar(total=counts["total"], show_eta=False)
                self._iteration_progress[it] = pb
                row = Horizontal(
                    Label(f"Iteration {it}", classes="iteration-label"),
                    pb,
                    classes="iteration-row",
                )
                progress_view.mount(row)
            else:
                pb = self._iteration_progress[it]
                pb.total = counts["total"]
                pb.progress = counts["done"]

    def process_responses(self, iteration: int, data: list[dict[str, Any]]) -> None:
        """Process response data and update the cached responses on the main thread."""
        for item in data:
            r_id = item.get("realization")
            if r_id is not None:
                self._responses[iteration, r_id].append(item)

    def on_tree_node_highlighted(
        self,
        event: Tree.NodeHighlighted[tuple[int, int] | None],
    ) -> None:
        """Handle tree node highlight to show response data."""
        if event.node.data is not None:
            self._selected_item = event.node.data
        else:
            self._selected_item = None
        self._update_response_viewer()

    def on_tree_node_selected(
        self,
        event: Tree.NodeSelected[tuple[int, int] | None],
    ) -> None:
        """Handle tree node selection to show response data."""
        if event.node.data is not None:
            self._selected_item = event.node.data
        else:
            self._selected_item = None
        self._update_response_viewer()

    def _update_response_viewer(self) -> None:
        """Update the response viewer for the selected realization."""
        item = self._selected_item
        viewer = self.query_one("#response-view", ResponseViewer)
        if item is None:
            viewer.update_response("Select a realization to view its last response.")
            return

        it, r_id = item
        state = self._statuses.get((it, r_id))
        if state:
            responses = self._responses.get((it, r_id), [])
            last_value = None
            key_fields = {}
            if responses:
                # Use only the last one for brevity
                last_resp = responses[-1]
                known_fields = {"realization", "source_step", "value", "type"}
                key_fields = {
                    k: v
                    for k, v in last_resp.items()
                    if k not in known_fields and v is not None
                }
                last_value = str(last_resp.get("value"))

            content = [
                f"Realization: {r_id}",
                f"Iteration: {it}",
                f"Status: {state['status']}",
                f"Responses Emitted: {len(responses)}",
                "",
                "Last Response:",
            ]
            if responses:
                for k, v in key_fields.items():
                    content.append(f"  {k}: {v}")
                content.append(f"  Value: {last_value}")
            else:
                content.append("  (None)")

            viewer.update_response("\n".join(content))


def start_monitor(
    api_url: str,
    experiment_id: str,
    execution_id: str | None = None,
    expected_count: int | None = None,
    num_iterations: int = 1,
) -> None:
    """Entry point for the monitor CLI command."""
    app = GertMonitorApp(
        api_url,
        experiment_id,
        execution_id,
        expected_count,
        num_iterations,
    )
    app.run()
