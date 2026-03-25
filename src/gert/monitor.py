# ruff: noqa: BLE001
"""CLI Monitor for GERT experiments using Textual."""

import json
import time
import urllib.request
from collections import defaultdict
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.error import URLError

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.widgets import Footer, Header, Label, ProgressBar, Static, Tree

if TYPE_CHECKING:
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


class NavigationTree(Tree[int]):
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
        height: 3;
        layout: horizontal;
        margin-bottom: 1;
    }

    .iteration-label {
        width: 15;
        content-align: right middle;
        padding-right: 1;
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
        expected_count: int | None = None,
    ) -> None:
        super().__init__()
        self.api_url = api_url
        self.experiment_id = experiment_id
        self.expected_count = expected_count
        self.status_url = f"{api_url}/experiments/{experiment_id}/status"
        self._statuses: dict[int, dict[str, Any]] = {}
        self._iteration_nodes: dict[int, TreeNode[int]] = {}
        self._realization_nodes: dict[int, TreeNode[int]] = {}
        self._iteration_progress: dict[int, ProgressBar] = {}
        self._exiting = False
        self._selected_realization_id: int | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="top-pane"):
            yield StateSummary("Waiting for data...", id="summary-container")
            yield ProgressView(id="progress-container")

        with Horizontal(id="bottom-pane"):
            yield NavigationTree(f"Experiment {self.experiment_id}", id="tree-view")
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

    @work(exclusive=True, thread=True)
    def poll_api(self) -> None:
        """Poll the API for status updates in a background thread."""
        while not self._exiting:
            try:
                req = urllib.request.Request(self.status_url)  # noqa: S310
                with urllib.request.urlopen(req, timeout=5) as response:  # noqa: S310
                    if response.getcode() == 200:
                        data = json.loads(response.read().decode("utf-8"))
                        self.call_from_thread(self.process_data, data)

                        if (
                            self.expected_count is not None
                            and len(self._statuses) >= self.expected_count
                            and all(
                                s["status"] in {"COMPLETED", "FAILED"}
                                for s in self._statuses.values()
                            )
                        ):
                            time.sleep(1)
                            self._exiting = True
                            self.call_from_thread(self.exit)
                            break
            except URLError:
                pass
            except Exception:  # noqa: S110
                pass

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

            self._statuses[r_id] = item
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
            if r_id not in self._realization_nodes:
                self._realization_nodes[r_id] = iter_node.add_leaf(label, data=r_id)
            else:
                self._realization_nodes[r_id].set_label(label)

        summary = self.query_one(StateSummary)
        summary.update_summary(state_counts)

        progress_view = self.query_one(ProgressView)
        for it, counts in iter_counts.items():
            if it not in self._iteration_progress:
                row = Horizontal(classes="iteration-row")
                row.mount(Label(f"Iteration {it}", classes="iteration-label"))
                pb = ProgressBar(total=counts["total"], show_eta=False)
                self._iteration_progress[it] = pb
                row.mount(pb)
                progress_view.mount(row)
            else:
                pb = self._iteration_progress[it]
                pb.total = counts["total"]
                pb.progress = counts["done"]

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted[int]) -> None:
        """Handle tree node highlight to show response data."""
        if event.node.data is not None:
            self._selected_realization_id = event.node.data
        else:
            self._selected_realization_id = None
        self._update_response_viewer()

    def on_tree_node_selected(self, event: Tree.NodeSelected[int]) -> None:
        """Handle tree node selection to show response data."""
        if event.node.data is not None:
            self._selected_realization_id = event.node.data
        else:
            self._selected_realization_id = None
        self._update_response_viewer()

    def _update_response_viewer(self) -> None:
        """Update the response viewer for the selected realization."""
        r_id = self._selected_realization_id
        viewer = self.query_one("#response-view", ResponseViewer)
        if r_id is None:
            viewer.update_response("Select a realization to view its last response.")
            return

        state = self._statuses.get(r_id)
        if state:
            viewer = self.query_one("#response-view", ResponseViewer)
            last_name = state.get("last_response_name")
            last_value = state.get("last_response_value")

            content = [
                f"Realization: {r_id}",
                f"Iteration: {state['iteration']}",
                f"Status: {state['status']}",
                f"Responses Emitted: {state.get('responses_emitted', 0)}",
                "",
                "Last Response:",
                f"  Name:  {last_name if last_name is not None else '-'}",
                f"  Value: {last_value if last_value is not None else '-'}",
            ]

            viewer.update_response("\n".join(content))


def start_monitor(
    api_url: str,
    experiment_id: str,
    expected_count: int | None = None,
) -> None:
    """Entry point for the monitor CLI command."""
    app = GertMonitorApp(api_url, experiment_id, expected_count)
    app.run()
