<script lang="ts">
import { onMount } from "svelte";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import UPlotChart from "./UPlotChart.svelte";
import { formatMetric } from "$lib/utils/formatting";

interface Props {
	data: { realization: number, value: number }[];
	mode: "jitter" | "kde" | "histogram";
	observations?: { value: number, std_dev: number }[];
	scale?: number;
	aspectRatio?: number;
	showObservations?: boolean;
	title?: string;
	valueRange?: [number, number];
}

let { data, mode, observations = [], scale = 1.0, aspectRatio = 2.0, showObservations = true, title = "", valueRange }: Props = $props();

// Math utilities
function getHistogram(vals: number[], bins = 15) {
	const min = Math.min(...vals);
	const max = Math.max(...vals);
	const range = max - min || 1;
	const step = range / bins;
	const counts = new Array(bins).fill(0);
	const centers = new Array(bins).fill(0).map((_, i) => min + (i + 0.5) * step);

	for (const val of vals) {
		let bin = Math.floor((val - min) / step);
		if (bin >= bins) bin = bins - 1;
		if (bin < 0) bin = 0;
		counts[bin]++;
	}
	return [centers, counts];
}

function getKDE(vals: number[], points = 100) {
	const min = Math.min(...vals);
	const max = Math.max(...vals);
	const range = max - min || 1;
	const pad = range * 0.2;
	const start = min - pad;
	const end = max + pad;
	const step = (end - start) / points;

	// Silverman's rule
	const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
	const variance = vals.reduce((a, b) => a + Math.pow(b - mean, 2), 0) / vals.length;
	const std = Math.sqrt(variance) || 0.1;
	const h = 1.06 * std * Math.pow(vals.length, -0.2) || 0.1;

	const xVals = new Array(points).fill(0).map((_, i) => start + i * step);
	const yVals = xVals.map(x => {
		let sum = 0;
		for (const v of vals) {
			const z = (x - v) / h;
			sum += Math.exp(-0.5 * z * z) / (Math.sqrt(2 * Math.PI));
		}
		return sum / (vals.length * h);
	});
	return [xVals, yVals];
}

let chartData = $derived.by(() => {
	const vals = data.map(d => d.value);
	if (vals.length === 0) return null;

	if (mode === "histogram") {
		return getHistogram(vals) as uPlot.AlignedData;
	} else if (mode === "kde") {
		return getKDE(vals) as uPlot.AlignedData;
	} else {
		// Jitter
		const xVals = vals.sort((a, b) => a - b);
		const yVals = xVals.map(() => Math.random());
		return [xVals, yVals] as uPlot.AlignedData;
	}
});

let chartOptions = $derived.by(() => {
	const fullTitle = title ? `${title} (${mode.toUpperCase()})` : mode.toUpperCase();
	const baseArea = 180000; // 600 * 300
	const w = Math.round(scale * Math.sqrt(baseArea * aspectRatio));
	const h = Math.round(scale * Math.sqrt(baseArea / aspectRatio));

	const base: uPlot.Options = {
		width: w,
		height: h,
		title: fullTitle,
		scales: {
			x: {
				time: false,
				range: (u, min, max) => {
					let rMin = valueRange ? valueRange[0] : min;
					let rMax = valueRange ? valueRange[1] : max;
					if (showObservations && observations.length > 0) {
						const obsVal = observations[0].value;
						if (obsVal < rMin) rMin = obsVal;
						if (obsVal > rMax) rMax = obsVal;
					}
					const pad = (rMax - rMin) * 0.1 || 1;
					return [rMin - pad, rMax + pad];
				}
			},
			y: { auto: true }
		},
		axes: [
			{
				stroke: "#94a3b8",
				grid: { stroke: "#334155", width: 1 },
				font: "10px JetBrains Mono",
				values: (u, vals) => vals.map(v => formatMetric(v))
			},
			{
				stroke: "#94a3b8",
				grid: { stroke: "#334155", width: 1 },
				font: "10px JetBrains Mono",
				values: (u, vals) => vals.map(v => formatMetric(v))
			}
		],
		series: [
			{
				value: (u, v) => formatMetric(v)
			},
			{
				label: mode === "histogram" ? "Frequency" : (mode === "kde" ? "Density" : "Jitter"),
				stroke: "#38bdf8",
				width: mode === "kde" ? 2 : 0,
				fill: mode === "histogram" ? "#38bdf833" : undefined,
				paths: mode === "histogram" ? uPlot.paths.bars!({ size: [0.8, 100] }) : undefined,
				points: {
					show: mode === "jitter",
					size: 6,
					stroke: "#38bdf8",
					fill: "#0f172a"
				},
				value: (u, v) => formatMetric(v)
			}
		]
	};

	// Add observations as markers if they exist and are toggled on
	if (showObservations && observations.length > 0) {
		const obsValue = observations[0].value;
		base.hooks = {
			draw: [
				(u) => {
					const { ctx } = u;
					ctx.save();
					ctx.strokeStyle = "#f43f5e"; // error color
					ctx.lineWidth = 2;
					ctx.setLineDash([5, 5]);

					const x = u.valToPos(obsValue, "x", true);

					// Draw line and text only if it falls inside the canvas
					if (x >= u.bbox.left && x <= u.bbox.left + u.bbox.width) {
						ctx.beginPath();
						ctx.moveTo(x, u.bbox.top);
						ctx.lineTo(x, u.bbox.top + u.bbox.height);
						ctx.stroke();

						ctx.fillStyle = "#f43f5e";
						ctx.font = "10px JetBrains Mono";
						ctx.textAlign = "center";
						ctx.fillText("OBS", x, u.bbox.top - 5);
					}

					ctx.restore();
				}
			]
		};
	}

	return base;
});
</script>

<div class="w-full h-full flex flex-col items-center">
	{#if chartData}
		<UPlotChart options={chartOptions} data={chartData} />
	{:else}
		<div class="text-surface-500 italic">No data to plot.</div>
	{/if}
</div>
