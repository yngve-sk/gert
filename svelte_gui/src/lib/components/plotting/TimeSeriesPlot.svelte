<script lang="ts">
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import UPlotChart from "./UPlotChart.svelte";
import { formatMetric } from "$lib/utils/formatting";

interface Props {
	data: any[];
	xCol: string;
	categoricalCols?: string[];
	observations?: any[];
	scale?: number;
	splitCol?: string | null;
	viewMode?: "combined" | "subplots";
	visibleSplits?: Set<string>;
	colorMap?: Record<string, string>;
	splitValues?: string[];
	showObservations?: boolean;
	iterationTitle?: string;
	aspectRatio?: number;
	yRange?: [number, number];
}

let {
	data,
	xCol,
	categoricalCols = [],
	observations = [],
	scale = 1.0,
	splitCol = null,
	viewMode = "combined",
	visibleSplits = new Set(),
	colorMap = {},
	splitValues = [],
	showObservations = true,
	iterationTitle = "",
	aspectRatio = 2.0,
	yRange
}: Props = $props();

const COLORS = [
	"#38bdf8", "#f43f5e", "#a3e635", "#fbbf24", "#c084fc",
	"#f472b6", "#2dd4bf", "#fb923c", "#818cf8", "#e879f9"
];

let charts = $derived.by(() => {
	if (!data || data.length === 0) return [];

	const rawXPoints = Array.from(new Set(data.map(d => d[xCol])));
	let isTime = false;
	let isCategorical = false;

	if (rawXPoints.length > 0) {
		const first = rawXPoints[0];
		if (typeof first === 'string' && isNaN(Number(first))) {
			const parsed = Date.parse(first);
			if (!isNaN(parsed)) {
				isTime = true;
			} else {
				isCategorical = true;
			}
		}
	}

	rawXPoints.sort((a: any, b: any) => {
		if (isTime) return Date.parse(a) - Date.parse(b);
		if (!isNaN(Number(a)) && !isNaN(Number(b))) return Number(a) - Number(b);
		return String(a).localeCompare(String(b));
	});

	const xData = rawXPoints.map((x, i) => {
		if (isTime) return Date.parse(x as string) / 1000;
		if (isCategorical) return i;
		const num = Number(x);
		return isNaN(num) ? i : num;
	});

	const buildChart = (subsetData: any[], title?: string, colorMap?: Record<string, string>) => {
		const realizations = Array.from(new Set(subsetData.map(d => d.realization))).sort((a, b) => a - b);
		const chartData: uPlot.AlignedData = [xData];
		const series: uPlot.Series[] = [
			{ value: isCategorical ? (u, v) => String(rawXPoints[Math.round(v)] || "") : undefined }
		];

		const activeSplitsInSubset = splitCol ? Array.from(new Set(subsetData.map(d => String(d[splitCol as string])))) : [null];

		for (const realId of realizations) {
			for (const sVal of activeSplitsInSubset) {
				const lineData = subsetData.filter(d =>
					d.realization === realId &&
					(!splitCol || String(d[splitCol as string]) === sVal)
				);

				if (lineData.length === 0) continue;

				const yVals = rawXPoints.map(x => {
					const row = lineData.find(d => d[xCol] === x);
					return row ? Number(row.value) : null;
				});

				chartData.push(yVals);

				const baseColor = (colorMap && sVal) ? colorMap[sVal] : "#38bdf8";

				series.push({
					label: `R${realId}` + (sVal ? ` (${sVal})` : ''),
					stroke: baseColor + "33", // 20% opacity
					width: 1,
					points: { show: false }
				});
			}
		}

		// Observations
		if (showObservations && observations.length > 0) {
			const obsYVals = rawXPoints.map(x => {
				const validObs = observations.filter(o => {
					if (splitCol && title) return String(o.key[splitCol as string]) === title;
					if (splitCol && visibleSplits.size > 0) return visibleSplits.has(String(o.key[splitCol as string]));
					return true;
				});
				const obs = validObs.find(o => String(o.key[xCol]) === String(x));
				return obs ? Number(obs.value) : null;
			});

			if (obsYVals.some(v => v !== null)) {
				chartData.push(obsYVals);
				series.push({
					label: "OBS",
					stroke: "#f43f5e",
					width: 0,
					points: {
						show: true,
						size: 8,
						stroke: "#f43f5e",
						fill: "#0f172a"
					}
				});
			}
		}

		series.forEach((s, i) => {
			if (i > 0 && !s.value) s.value = (u, v) => formatMetric(v);
		});

		const fullTitle = title ? `${iterationTitle}: ${title}` : iterationTitle;
		const baseArea = viewMode === "subplots" ? 100000 : 320000;
		const w = Math.round(scale * Math.sqrt(baseArea * aspectRatio));
		const h = Math.round(scale * Math.sqrt(baseArea / aspectRatio));

		const options: uPlot.Options = {
			width: w,
			height: h,
			title: fullTitle,
			scales: {
				x: { time: isTime },
				y: {
					auto: !yRange,
					range: yRange ? [yRange[0], yRange[1]] : undefined
				}
			},
			axes: [
				{
					stroke: "#94a3b8",
					grid: { stroke: "#334155", width: 1 },
					font: "10px JetBrains Mono",
					label: xCol.toUpperCase(),
					values: isCategorical ? (u, vals) => vals.map(v => String(rawXPoints[Math.round(v)] || "")) : undefined
				},
				{
					stroke: "#94a3b8",
					grid: { stroke: "#334155", width: 1 },
					font: "10px JetBrains Mono",
					values: (u, vals) => vals.map(v => formatMetric(v))
				}
			],
			series,
			legend: { show: false }
		};

		return { chartData, options, id: title || "main" };
	};

	if (viewMode === "combined") {
		let colorMap: Record<string, string> = {};
		if (splitCol) {
			splitValues.forEach((v, i) => { colorMap[v] = COLORS[i % COLORS.length]; });
		}

		const filtered = splitCol ? data.filter(d => visibleSplits.has(String(d[splitCol as string]))) : data;
		return [buildChart(filtered, undefined, colorMap)];
	} else {
		// Subplots
		const result = [];
		for (const sVal of splitValues) {
			if (!visibleSplits.has(sVal)) continue;
			const filtered = data.filter(d => String(d[splitCol as string]) === sVal);
			result.push(buildChart(filtered, sVal, colorMap)); // title is the sub-category
		}
		return result;
	}
});
</script>

<div class="w-full h-full flex flex-col min-h-0">
	<!-- Plot area -->
	<div class="flex-auto overflow-x-auto overflow-y-hidden p-4 w-full">
		<div class="flex flex-row gap-4 items-start justify-start content-start min-w-max">
			{#if charts.length > 0}
				{#each charts as chart (chart.id)}
					<div class="bg-surface-950 p-2 rounded-lg border border-surface-800 shadow-md shrink-0">
						{#key chart.id + String(viewMode)}
							<UPlotChart options={chart.options} data={chart.chartData} />
						{/key}
					</div>
				{/each}
			{:else}
				<div class="text-surface-500 italic mt-10">No data visible. Select categories above.</div>
			{/if}
		</div>
	</div>
</div>
