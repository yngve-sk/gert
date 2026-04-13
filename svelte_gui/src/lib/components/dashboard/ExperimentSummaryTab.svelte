<script lang="ts">
import { onMount, untrack } from "svelte";
import { getUpdateMetadata, type UpdateMetadata } from "$lib/api/client";
import UPlotChart from "$lib/components/plotting/UPlotChart.svelte";
import { formatMetric } from "$lib/utils/formatting";
import type { RealizationStatus } from "$lib/stores/websocket.svelte";

interface Props {
	experimentId: string;
	executionId: string;
	totalIterations: number;
	events: RealizationStatus[];
}

let { experimentId, executionId, totalIterations, events }: Props = $props();

let updateMetadatas = $state<Record<number, UpdateMetadata>>({});
let isFetching = false;

async function fetchMissingUpdates() {
	if (isFetching) return;
	isFetching = true;

	try {
		let fetcher = window.fetch;
		if (window.location.pathname.includes("/_app/")) {
			fetcher = (input: RequestInfo | URL, init?: RequestInit) => {
				const targetUrl = new URL(input.toString(), window.location.origin);
				return window.fetch(targetUrl, init);
			};
		}

		let didUpdate = false;
		const fetches = [];
		for (let i = 0; i < totalIterations - 1; i++) {
			if (updateMetadatas[i] && updateMetadatas[i].status === "COMPLETED") {
				continue;
			}

			// The update "i" produces ensemble "i + 1", so metadata lives there
			fetches.push(
				getUpdateMetadata(experimentId, executionId, i + 1, fetcher)
					.then((meta) => {
						updateMetadatas[i] = meta;
						didUpdate = true;
					})
					.catch((e) => {
						// Expected if the update hasn't run yet
					})
			);
		}

		await Promise.all(fetches);
		if (didUpdate) {
			// Trigger reactivity on the object
			updateMetadatas = { ...updateMetadatas };
		}
	} finally {
		isFetching = false;
	}
}

// React to websocket events: if the events array grows or changes, we might have new updates
$effect(() => {
	const currentEvents = events;
	untrack(() => {
		// In an untracked block, we trigger the fetch logic
		// which will itself decide if there's anything new to actually grab.
		fetchMissingUpdates();
	});
});

onMount(() => {
	fetchMissingUpdates();
});

// Prepare uPlot data
let plotData = $derived.by(() => {
	const xVals: number[] = [];
	const misfitVals: number[] = [];
	const varianceVals: number[] = [];

	console.log("plotData refresh")
	for (let i = 0; i < totalIterations - 1; i++) {
		console.log(`plotData refresh iteration ${i}`)
		const meta = updateMetadatas[i];
		if (meta && meta.status === "COMPLETED") {
			console.log(`plotData refresh iteration ${i} x`)
			xVals.push(i);

			// Try to find a representative misfit value
			const misfit = meta.metrics.average_absolute_misfit || meta.metrics.average_misfit || meta.metrics.misfit_bias || 0;
			misfitVals.push(misfit);

			// Try to find variance
			const variance = meta.metrics.posterior_variance || meta.metrics.variance || meta.metrics.prior_variance || 0;
			varianceVals.push(variance);
		}
	}

	if (xVals.length === 0) return null;

	return [xVals, misfitVals, varianceVals] as uPlot.AlignedData;
});

const plotOptions = {
	width: 600,
	height: 300,
	title: "Convergence Metrics",
	hooks: {
		// This hook allows drawing custom elements on the chart canvas
		draw: [
			(u: uPlot) => {
				const { ctx } = u;
				const { top, left, width, height } = u.bbox;

				// Find the y-pixel position for the value 0 on the 'y' scale
				const y0 = u.valToPos(0, 'y');

				// Only draw the line if it's visible within the plot area
				if (y0 >= top && y0 <= top + height) {
					ctx.save();
					ctx.beginPath();
					ctx.lineWidth = 1;
					// A subtle gray that matches the grid lines
					ctx.strokeStyle = '#334155';
					ctx.moveTo(left, y0);
					ctx.lineTo(left + width, y0);
					ctx.stroke();
					ctx.restore();
				}
			},
		],
	},
	axes: [
		{
			label: "Update",
			stroke: "#94a3b8",
			grid: { stroke: "#334155", width: 1 },
			ticks: { stroke: "#334155", width: 1 },
			font: "10px JetBrains Mono",
			// Generate discrete ticks for exactly the integer values present in data
			splits: (u: any, axisIdx: number, scaleMin: number, scaleMax: number) => {
				const vals = u.data[0];
				return vals;
			},
			values: (u: any, vals: any[]) => vals.map(v => `${v}→${v+1}`)
		},
		{
			label: "Avg Misfit",
			stroke: "#38bdf8", // primary
			grid: { stroke: "#334155", width: 1 },
			ticks: { stroke: "#334155", width: 1 },
			font: "10px JetBrains Mono",
			values: (u: any, vals: any[]) => vals.map(v => formatMetric(v))
		},
		{
			side: 1, // right axis
			label: "Variance",
			stroke: "#f43f5e", // error
			grid: { show: false },
			ticks: { stroke: "#334155", width: 1 },
			font: "10px JetBrains Mono",
			values: (u: any, vals: any[]) => vals.map(v => formatMetric(v))
		}
	],
	series: [
		{
			label: "Update",
			value: (u: any, v: number) => `${v}→${v+1}`
		},
		{
			label: "Avg Misfit",
			stroke: "#38bdf8",
			width: 2,
			points: { show: true, size: 6, width: 2, stroke: "#38bdf8", fill: "#0f172a" },
			value: (u: any, v: number) => formatMetric(v)
		},
		{
			label: "Variance",
			stroke: "#f43f5e",
			width: 2,
			scale: "y2",
			points: { show: true, size: 6, width: 2, stroke: "#f43f5e", fill: "#0f172a" },
			value: (u: any, v: number) => formatMetric(v)
		}
	],
	scales: {
		"x": { time: false },
		"y": {
			auto: true,
			// This function modifies the auto-scaled range to ensure
			// the y-axis always includes 0. This effectively anchors
			// the axis at 0, placing it at the bottom for positive data.
			range(u: uPlot, dataMin: number, dataMax: number): [number, number] {
				const min = Math.min(dataMin, 0);
				const max = Math.max(dataMax, 0);

				// Add a little padding to the top and bottom
				const padding = (max - min) * 0.1 || 1;

				return [min - padding, max + padding];
			},
		},
		"y2": { auto: true }
	}
};
</script>

<div class="h-full w-full bg-surface-900 border border-surface-700 rounded-lg p-4 flex flex-col gap-4">
	<header class="flex justify-between items-center pb-3 border-b border-surface-700">
		<div>
			<h2 class="text-lg font-bold text-tertiary-400 flex items-center gap-2">
				<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
					<path d="M2 11a1 1 0 011-1h2a1 1 0 011 1v5a1 1 0 01-1 1H3a1 1 0 01-1-1v-5zM8 7a1 1 0 011-1h2a1 1 0 011 1v9a1 1 0 01-1 1H9a1 1 0 01-1-1V7zM14 4a1 1 0 011-1h2a1 1 0 011 1v12a1 1 0 01-1 1h-2a1 1 0 01-1-1V4z" />
				</svg>
				Experiment Summary
			</h2>
			<p class="text-xs text-surface-400 mt-1">Overview of algorithm convergence metrics.</p>
		</div>
	</header>

	<section class="bg-surface-800 border border-surface-700 rounded p-4 flex flex-col items-center justify-center min-h-[400px]">
		{#if plotData}
			<div class="w-full flex justify-center">
				<UPlotChart options={plotOptions} data={plotData} />
			</div>
		{:else}
			<div class="flex-auto flex flex-col items-center justify-center text-surface-500 text-sm italic">
				<svg xmlns="http://www.w3.org/2000/svg" class="h-12 w-12 mb-4 text-surface-700" fill="none" viewBox="0 0 24 24" stroke="currentColor">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 12l3-3 3 3 4-4M8 21l4-4 4 4M3 4h18M4 4h16v12a1 1 0 01-1 1H5a1 1 0 01-1-1V4z" />
				</svg>
				<p>No completed updates to plot yet.</p>
				<p class="text-xs mt-1">Convergence metrics will appear here automatically.</p>
			</div>
		{/if}
	</section>
</div>
