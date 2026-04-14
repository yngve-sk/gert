"""Plotting overlay for the GERT CLI monitor."""

import contextlib
import io
import json
import typing
import urllib.request
from typing import TYPE_CHECKING
from urllib.error import URLError

import polars as pl
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, LoadingIndicator, OptionList
from textual.widgets.option_list import Option
from textual_plot import HiResMode, PlotWidget

if TYPE_CHECKING:
    from gert.monitor import NodeData


class PlotterScreen(ModalScreen[None]):
    """Overlay screen for plotting parameters and responses."""

    BINDINGS: typing.ClassVar[list[typing.Any]] = [
        Binding("p", "dismiss", "Close Plotter", show=True),
        Binding("escape", "dismiss", "Close Plotter", show=True),
        Binding("x", "cycle_x_axis", "Cycle X-Axis", show=True),
        Binding("less_than", "cycle_z_down", "Prev Z/Layer", show=True),
        Binding("greater_than", "cycle_z_up", "Next Z/Layer", show=True),
        Binding("bracketleft", "cycle_left_down", "Prev Iter (L)"),
        Binding("bracketright", "cycle_left_up", "Next Iter (L)"),
        Binding("left_curly_bracket", "cycle_right_down", "Prev Iter (R)"),
        Binding("right_curly_bracket", "cycle_right_up", "Next Iter (R)"),
    ]

    CSS = """
    PlotterScreen {
        align: center middle;
        background: $background 80%;
    }

    #plotter-container {
        width: 90%;
        height: 90%;
        border: solid green;
        background: $surface;
    }

    #plot-selector-pane {
        width: 30%;
        border-right: dashed green;
    }

    #plot-canvas-pane {
        width: 70%;
        layout: vertical;
    }

    #plot-title {
        height: 1;
        content-align: center middle;
        background: $accent;
        color: $text;
        text-style: bold;
    }

    #plot-loading {
        content-align: center middle;
        height: 1fr;
    }

    #plot-multiples {
        height: 1fr;
    }

    PlotWidget {
        height: 1fr;
    }

    #plot-footer {
        height: 1;
        content-align: left middle;
        color: $text-muted;
    }

    .panel-title {
        height: 1;
        content-align: center middle;
        background: $primary-background;
        color: $text;
        text-style: bold;
    }
    """

    def __init__(
        self,
        api_url: str,
        experiment_id: str,
        execution_id: str,
        scope_node: "NodeData",
        total_iterations: int = 0,
    ) -> None:
        """Initialize the plotter screen."""
        super().__init__()
        self.api_url = api_url
        self.experiment_id = experiment_id
        self.execution_id = execution_id
        self.scope_node = scope_node
        self.total_iterations = total_iterations

        self.is_experiment = scope_node.node_type == "experiment"
        self.iter_left = 0
        self.iter_right = max(0, total_iterations - 1)

        self.resps_cache: dict[int, pl.DataFrame] = {}
        self.params_cache: dict[int, pl.DataFrame] = {}

        self.selected_var_type: str | None = None  # "response" or "parameter"
        self.selected_var_filters: dict[str, str] | str | None = (
            None  # either param name or response filters
        )

        self.x_axes: list[str] = []
        self.current_x_idx: int = 0

        self.z_layers: list[int] = []
        self.current_z_idx: int = 0

        self._last_manifest: dict[str, float] = {}

    def compose(self) -> ComposeResult:
        """Compose the plotter layout.

        Yields:
            The layout widgets.
        """
        with Horizontal(id="plotter-container"):
            with Vertical(id="plot-selector-pane"):
                yield Label("Variables", id="plot-title")
                yield OptionList(id="variable-list")
            with Vertical(id="plot-canvas-pane"):
                if self.is_experiment:
                    with Horizontal(id="plot-multiples"):
                        with Vertical():
                            yield Label(
                                "Iter Left",
                                id="plot-title-left",
                                classes="panel-title",
                            )
                            yield PlotWidget(id="main-plot-left")
                        with Vertical():
                            yield Label(
                                "Iter Right",
                                id="plot-title-right",
                                classes="panel-title",
                            )
                            yield PlotWidget(id="main-plot-right")
                    yield Label(
                        "Use [ / ] to cycle left iter, { / } for right iter",
                        id="plot-footer",
                    )
                else:
                    yield LoadingIndicator(id="plot-loading")
                    yield PlotWidget(id="main-plot")
                    yield Label("Loading data...", id="plot-footer")

    def on_mount(self) -> None:
        """Fetch data when the screen mounts."""
        self.log.info(
            f"PlotterScreen mounted for {self.scope_node.node_type} "
            f"(iter={self.scope_node.iteration})",
        )
        if not self.is_experiment:
            self.query_one("#main-plot").display = False
        self.fetch_data()
        self.set_interval(1.0, self.poll_manifest)

    @work(exclusive=True, thread=True)
    def poll_manifest(self) -> None:
        """Poll the manifest endpoint to check for updates."""
        if self.is_experiment:
            # Manifest polling per iteration doesn't easily map to experiment mode
            return

        it = self.scope_node.iteration
        manifest_url = (
            f"{self.api_url}/api/experiments/{self.experiment_id}/"
            f"executions/{self.execution_id}/ensembles/{it}/manifest"
        )
        try:
            req = urllib.request.Request(manifest_url)  # noqa: S310
            with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
                if resp.getcode() == 200:
                    manifest = json.loads(resp.read().decode("utf-8"))
                    if manifest != self._last_manifest:
                        self._last_manifest = manifest
                        self.fetch_data()
        except URLError:
            pass

    @work(exclusive=True, thread=True)
    def fetch_data(self) -> None:  # noqa: C901
        """Fetch parameters and responses for the current iteration."""
        iters_to_fetch = (
            [self.iter_left, self.iter_right]
            if self.is_experiment
            else [self.scope_node.iteration]
        )

        for it in iters_to_fetch:
            if it in self.resps_cache and it in self.params_cache:
                continue

            resps_url = (
                f"{self.api_url}/api/experiments/{self.experiment_id}/"
                f"executions/{self.execution_id}/ensembles/{it}/responses"
            )
            params_url = (
                f"{self.api_url}/api/experiments/{self.experiment_id}/"
                f"executions/{self.execution_id}/ensembles/{it}/parameters"
            )

            resps_df = pl.DataFrame()
            params_df = pl.DataFrame()

            try:
                req = urllib.request.Request(resps_url)  # noqa: S310
                with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                    if resp.getcode() == 200:
                        data_bytes = resp.read()
                        if data_bytes:
                            resps_df = pl.read_parquet(io.BytesIO(data_bytes))
            except URLError:
                pass
            except Exception as e:  # noqa: BLE001
                self.log.warning(f"Failed to fetch responses for iter {it}: {e}")

            try:
                req = urllib.request.Request(params_url)  # noqa: S310
                with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                    if resp.getcode() == 200:
                        data_bytes = resp.read()
                        if data_bytes:
                            params_df = pl.read_parquet(io.BytesIO(data_bytes))
            except URLError:
                pass
            except Exception as e:  # noqa: BLE001
                self.log.warning(f"Failed to fetch parameters for iter {it}: {e}")

            self.resps_cache[it] = resps_df
            self.params_cache[it] = params_df

        self.app.call_from_thread(self._on_data_fetched)

    def _on_data_fetched(self) -> None:  # noqa: C901
        """Handle the fetched data and populate the UI."""
        if not self.is_experiment:
            self.query_one("#plot-loading").display = False
            self.query_one("#main-plot").display = True

        # Use left iter or scope iter to populate the selector pane options
        target_iter = (
            self.iter_left if self.is_experiment else self.scope_node.iteration
        )
        df_resp = self.resps_cache.get(target_iter, pl.DataFrame())
        df_param = self.params_cache.get(target_iter, pl.DataFrame())

        if not df_resp.is_empty():
            meta_cols = {
                "realization",
                "value",
                "std_dev",
                "source_step",
                "type",
                "value_obs",
            }
            key_cols = [c for c in df_resp.columns if c not in meta_cols]

            # Auto-cast purely numeric columns to Float64 so they can be X-axes
            for c in key_cols:
                s = df_resp.get_column(c)
                if s.dtype not in {pl.Float64, pl.Float32, pl.Int64, pl.Int32}:
                    with contextlib.suppress(Exception):
                        s_cast = s.cast(pl.Float64, strict=False)
                        if (
                            s.null_count() == s_cast.null_count()
                            and not s_cast.is_null().all()
                        ):
                            df_resp = df_resp.with_columns(s_cast.alias(c))

        # Update variable list if not previously loaded
        opt_list = self.query_one("#variable-list", OptionList)
        previous_highlighted_id = None
        if opt_list.highlighted is not None:
            with contextlib.suppress(Exception):
                previous_highlighted_id = opt_list.get_option_at_index(
                    opt_list.highlighted,
                ).id

        # Build Options dynamically
        options = []

        # Responses
        if not df_resp.is_empty():
            meta_cols = {
                "realization",
                "value",
                "std_dev",
                "source_step",
                "type",
                "value_obs",
            }
            key_cols = [c for c in df_resp.columns if c not in meta_cols]

            # Find purely categorical string columns (those that couldn't be cast)
            cat_cols = [
                c
                for c in key_cols
                if df_resp.get_column(c).dtype
                not in {pl.Float64, pl.Float32, pl.Int64, pl.Int32}
            ]

            if cat_cols:
                unique_combos = df_resp.select(cat_cols).unique().to_dicts()
                # Sort combos for stable display
                unique_combos.sort(key=lambda d: str(list(d.values())))
                for combo in unique_combos:
                    opt_id = "resp_" + json.dumps(combo)
                    resp_name = combo.pop("response", "Unknown")
                    details = ", ".join(
                        f"{k}={v}" for k, v in combo.items() if v is not None
                    )
                    label = (
                        f"🔥 {resp_name} ({details})" if details else f"🔥 {resp_name}"
                    )
                    options.append(Option(label, id=opt_id))
            else:
                options.append(Option("🔥 all", id="resp_all"))

        # Parameters
        if not df_param.is_empty():
            param_cols = [
                c for c in df_param.columns if c not in {"realization", "i", "j", "k"}
            ]
            options.extend(
                Option(f"💧 {p}", id=f"param_{p}") for p in sorted(param_cols)
            )

        if options:
            opt_list.clear_options()
            opt_list.add_options(options)

            # Restore highlighted option
            if previous_highlighted_id is not None:
                for i, opt in enumerate(options):
                    if opt.id == previous_highlighted_id:
                        opt_list.highlighted = i
                        break

            if self.selected_var_type is None:
                self.query_one("#plot-footer", Label).update(
                    "Data loaded. Select a variable.",
                )
        else:
            opt_list.clear_options()
            opt_list.add_option(Option("No data available", disabled=True))
            self.query_one("#plot-footer", Label).update("No data available.")

        # Re-render if something was selected
        if self.selected_var_type is not None:
            self._prepare_plot()

    def on_option_list_option_highlighted(
        self,
        event: OptionList.OptionHighlighted,
    ) -> None:
        """Handle variable selection on highlight."""
        if event.option is None:
            return
        opt_id = event.option.id
        if not opt_id:
            return

        if opt_id.startswith("resp_"):
            self.selected_var_type = "response"
            if opt_id == "resp_all":
                self.selected_var_filters = {}
            else:
                self.selected_var_filters = json.loads(opt_id[5:])
        elif opt_id.startswith("param_"):
            self.selected_var_type = "parameter"
            self.selected_var_filters = opt_id[6:]
        else:
            return

        self._prepare_plot()

    async def action_dismiss(self, result: None = None) -> None:
        """Close the plotter screen."""
        self.log.info("PlotterScreen dismiss requested")
        self.dismiss(result)

    def action_cycle_x_axis(self) -> None:
        """Cycle through available X-axes."""
        if not self.x_axes or len(self.x_axes) <= 1:
            return
        self.current_x_idx = (self.current_x_idx + 1) % len(self.x_axes)
        self._render_plot()

    def action_cycle_z_up(self) -> None:
        """Cycle up through Z-layers."""
        if not self.z_layers or len(self.z_layers) <= 1:
            return
        self.current_z_idx = min(len(self.z_layers) - 1, self.current_z_idx + 1)
        self._render_plot()

    def action_cycle_z_down(self) -> None:
        """Cycle down through Z-layers."""
        if not self.z_layers or len(self.z_layers) <= 1:
            return
        self.current_z_idx = max(0, self.current_z_idx - 1)
        self._render_plot()

    def action_cycle_left_down(self) -> None:
        if self.is_experiment and self.iter_left > 0:
            self.iter_left -= 1
            self.fetch_data()

    def action_cycle_left_up(self) -> None:
        if self.is_experiment and self.iter_left < self.total_iterations - 1:
            self.iter_left += 1
            self.fetch_data()

    def action_cycle_right_down(self) -> None:
        if self.is_experiment and self.iter_right > 0:
            self.iter_right -= 1
            self.fetch_data()

    def action_cycle_right_up(self) -> None:
        if self.is_experiment and self.iter_right < self.total_iterations - 1:
            self.iter_right += 1
            self.fetch_data()

    def _get_filtered_df(
        self,
        df_resp: pl.DataFrame,
        df_param: pl.DataFrame,
    ) -> pl.DataFrame:
        """Apply variable and scope filters to get final pl.DataFrame."""
        df = None
        if self.selected_var_type == "response" and not df_resp.is_empty():
            df = df_resp
            if isinstance(self.selected_var_filters, dict):
                for k, v in self.selected_var_filters.items():
                    if k in df.columns:
                        df = df.filter(pl.col(k) == v)
        elif self.selected_var_type == "parameter" and not df_param.is_empty():
            cols = ["realization"]
            cols.extend(c for c in ["i", "j", "k"] if c in df_param.columns)
            if isinstance(self.selected_var_filters, str):
                cols.append(self.selected_var_filters)
                df = df_param.select(cols)

        if df is None or df.is_empty():
            return pl.DataFrame()

        # Contextual Filtering (Scope)
        if (
            self.scope_node.node_type in {"realization", "step"}
            and self.scope_node.realization_id is not None
            and "realization" in df.columns
        ):
            df = df.filter(pl.col("realization") == self.scope_node.realization_id)

        if (
            self.scope_node.node_type == "step"
            and self.scope_node.step_name
            and "source_step" in df.columns
        ):
            df = df.filter(pl.col("source_step") == self.scope_node.step_name)

        return df

    def _prepare_plot(self) -> None:
        """Prepare axes based on the left/main iteration data."""
        if self.selected_var_type is None:
            return

        target_iter = (
            self.iter_left if self.is_experiment else self.scope_node.iteration
        )
        df_resp = self.resps_cache.get(target_iter, pl.DataFrame())
        df_param = self.params_cache.get(target_iter, pl.DataFrame())
        df = self._get_filtered_df(df_resp, df_param)

        if df.is_empty():
            self.query_one("#plot-footer", Label).update("No data in current scope.")
            if self.is_experiment:
                self.query_one("#main-plot-left", PlotWidget).clear()
                self.query_one("#main-plot-right", PlotWidget).clear()
            else:
                self.query_one("#main-plot", PlotWidget).clear()
            return

        # Determine Dimensionality
        has_i = "i" in df.columns
        has_j = "j" in df.columns
        has_k = "k" in df.columns

        self.z_layers = []
        self.current_z_idx = 0
        if has_k:
            self.z_layers = sorted(df.get_column("k").drop_nulls().unique().to_list())

        self.x_axes = []
        self.current_x_idx = 0

        if not (has_i and has_j):
            val_col = (
                "value"
                if self.selected_var_type == "response"
                else str(self.selected_var_filters)
            )
            potential_x = []
            for col in df.columns:
                if col in {"realization", "response", "source_step", "type", val_col}:
                    continue
                if df.get_column(col).dtype in {
                    pl.Float64,
                    pl.Float32,
                    pl.Int64,
                    pl.Int32,
                }:
                    potential_x.append(col)
            if potential_x:
                self.x_axes = potential_x
            else:
                self.x_axes = ["_index"]  # Fallback

        self._render_plot()

    def _render_plot(self) -> None:
        """Render the plots."""
        if self.selected_var_type is None:
            return

        footer_text = f"Variable: {self.selected_var_filters}"

        if self.is_experiment:
            self._render_single_plot(self.iter_left, "left")
            self._render_single_plot(self.iter_right, "right")

            if self.x_axes:
                footer_text += (
                    f" | X-Axis: {self.x_axes[self.current_x_idx]} (use 'x' to cycle)"
                )
            if self.z_layers:
                footer_text += (
                    f" | Z-Layer: {self.z_layers[self.current_z_idx]} "
                    "(use < > to change)"
                )

            footer_text += " | [ / ] Cycle Left Iter | { / } Cycle Right Iter"
            self.query_one("#plot-footer", Label).update(footer_text)
        else:
            footer_text = self._render_single_plot(self.scope_node.iteration, "main")
            if footer_text:
                self.query_one("#plot-footer", Label).update(footer_text)

    def _render_single_plot(self, iteration: int, mode: str) -> str:  # noqa: C901
        """Render a single PlotWidget given iteration and mode ('left', etc.)."""
        df_resp = self.resps_cache.get(iteration, pl.DataFrame())
        df_param = self.params_cache.get(iteration, pl.DataFrame())
        df = self._get_filtered_df(df_resp, df_param)

        widget_id = f"#main-plot-{mode}" if mode in {"left", "right"} else "#main-plot"
        title_id = f"#plot-title-{mode}" if mode in {"left", "right"} else None

        pw = self.query_one(widget_id, PlotWidget)
        pw.clear()

        if title_id:
            self.query_one(title_id, Label).update(f"Iteration {iteration}")

        if df.is_empty():
            return ""

        val_col = (
            "value"
            if self.selected_var_type == "response"
            else str(self.selected_var_filters)
        )

        has_i = "i" in df.columns
        has_j = "j" in df.columns

        footer_text = f"Variable: {self.selected_var_filters}"

        if has_i and has_j:
            # 2D/3D Heatmap
            if self.z_layers:
                z_val = self.z_layers[self.current_z_idx]
                df = df.filter(pl.col("k") == z_val)
                footer_text += f" | Z-Layer (k): {z_val} (use < > to change)"

            vmin = float(typing.cast("float", df.get_column(val_col).min()))
            vmax = float(typing.cast("float", df.get_column(val_col).max()))
            vrange = vmax - vmin if vmax != vmin else 1.0

            colors = ["blue", "cyan", "green", "yellow", "red"]

            if (
                "realization" in df.columns
                and df.get_column("realization").n_unique() > 1
            ):
                df = df.group_by(["i", "j"]).agg(pl.col(val_col).mean())
                footer_text += " | (Ensemble Mean shown)"

            for b in range(len(colors)):
                lower = vmin + (b / len(colors)) * vrange
                upper = vmin + ((b + 1) / len(colors)) * vrange
                if b == len(colors) - 1:
                    bucket_df = df.filter(pl.col(val_col) >= lower)
                else:
                    bucket_df = df.filter(
                        (pl.col(val_col) >= lower) & (pl.col(val_col) < upper),
                    )

                if not bucket_df.is_empty():
                    pw.scatter(
                        bucket_df.get_column("i").to_list(),
                        bucket_df.get_column("j").to_list(),
                        marker=".",
                        marker_style=colors[b],
                        label=f"{lower:.2f}-{upper:.2f}",
                        hires_mode=HiResMode.BRAILLE,
                    )

            pw.set_xlabel("i")
            pw.set_ylabel("j")

        else:
            # 1D / Scalar Series
            x_axis = self.x_axes[self.current_x_idx]
            footer_text += f" | X-Axis: {x_axis} (use 'x' to cycle)"

            realizations = [None]
            if "realization" in df.columns:
                realizations = sorted(
                    df.get_column("realization").drop_nulls().unique().to_list(),
                )

            pw.set_xlabel(x_axis)
            pw.set_ylabel(val_col)

            for r in realizations:
                r_df = df if r is None else df.filter(pl.col("realization") == r)

                y_series = r_df.get_column(val_col)
                if y_series.dtype in {pl.List(pl.Float64), pl.List(pl.Float32)}:
                    y_vals = y_series.to_list()[0]
                    x_vals = list(range(len(y_vals)))
                else:
                    y_vals = y_series.to_list()
                    if x_axis == "_index":
                        x_vals = list(range(len(y_vals)))
                    else:
                        x_vals = r_df.get_column(x_axis).to_list()
                        sorted_pairs = sorted(zip(x_vals, y_vals, strict=False))
                        x_vals = [p[0] for p in sorted_pairs]
                        y_vals = [p[1] for p in sorted_pairs]

                label = f"Real {r}" if r is not None and len(realizations) > 1 else None

                with contextlib.suppress(Exception):
                    pw.plot(
                        x_vals,
                        y_vals,
                        label=label,
                        hires_mode=HiResMode.BRAILLE,
                    )

        return footer_text
