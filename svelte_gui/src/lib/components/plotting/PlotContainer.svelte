<script lang="ts">
import type uPlot from "uplot";
import type { ObservationSummary } from "$lib/api/client";
// biome-ignore lint/correctness/noUnusedImports: used in HTML template
import UPlotEngine from "./engines/UPlotEngine.svelte";

interface Props {
	summaries: { iteration: number; data: ObservationSummary }[];
}
let { summaries }: Props = $props();

// Process data for uPlot
// The first array in `data` represents the X axis (Iterations)
// Subsequent arrays represent Y axis series (Misfit, Absolute Residual, etc.)
// biome-ignore lint/correctness/noUnusedVariables: used in HTML template bindings
let plotData: uPlot.AlignedData = $derived.by(() => {
	const sorted = [...summaries].sort((a, b) => a.iteration - b.iteration);

	const iterations = sorted.map((s) => s.iteration);
	const avgMisfit = sorted.map((s) => s.data.average_misfit);
	const avgAbsMisfit = sorted.map((s) => s.data.average_absolute_misfit);

	return [iterations, avgMisfit, avgAbsMisfit];
});

// biome-ignore lint/correctness/noUnusedVariables: used in HTML template bindings
let plotOpts: uPlot.Options = {
	title: "Global Convergence Metrics",
	id: "convergence-plot",
	class: "convergence-plot",
	width: 800,
	height: 300,
	axes: [
		{
			label: "Iteration",
			stroke: "#9CA3AF", // text-surface-400
			grid: { show: false },
			ticks: { show: true, stroke: "#374151" }, // surface-700
			space: 40,
		},
		{
			label: "Value",
			stroke: "#9CA3AF",
			grid: { show: true, stroke: "#374151", width: 1 },
			ticks: { show: true, stroke: "#374151" },
		},
	],
	scales: {
		x: { time: false }, // X-axis is purely numeric iterations, not timestamps
		y: { auto: true },
	},
	series: [
		{ label: "Iteration" }, // X axis
		{
			label: "Avg Misfit",
			stroke: "#3B82F6", // Primary blue
			width: 2,
			points: { size: 6, fill: "#3B82F6" },
		},
		{
			label: "Avg Abs Misfit",
			stroke: "#F59E0B", // Warning yellow
			width: 2,
			points: { size: 6, fill: "#F59E0B" },
		},
	],
};
</script>

<div class="w-full h-full flex flex-col">
	{#if summaries.length === 0}
		<div class="flex-auto flex items-center justify-center border border-dashed border-surface-700 rounded p-8">
			<span class="text-surface-500 italic text-sm">No convergence data available yet.</span>
		</div>
	{:else}
		<UPlotEngine data={plotData} opts={plotOpts} />
	{/if}
</div>
