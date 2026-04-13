<script lang="ts">
import { onDestroy, untrack } from "svelte";
import { page } from "$app/state";
import { goto } from "$app/navigation";
import { fetchParquet } from "$lib/api/client";
import DeckGLPlot from "$lib/components/plotting/DeckGLPlot.svelte";
import DistributionPlot from "$lib/components/plotting/DistributionPlot.svelte";
import TimeSeriesPlot from "$lib/components/plotting/TimeSeriesPlot.svelte";

interface Props {
	experimentId: string;
	executionId: string;
	totalIterations: number;
	dataType: "responses" | "parameters";
	observations?: any[];
}

let { experimentId, executionId, totalIterations, dataType, observations = [] }: Props = $props();

// Default to the last available iteration
let selectedIterations = $state<number[]>([totalIterations > 0 ? totalIterations - 1 : 0]);
let parsedData = $state<Record<number, any[]>>({});
let loading = $state<Record<number, boolean>>({});
let error = $state<Record<number, string | null>>({});

let selectedVar = $state<string | null>(page.url.searchParams.get("var"));
let plotMode = $state<"jitter" | "kde" | "histogram">(
	(page.url.searchParams.get("mode") as any) || "histogram"
);
let pollInterval: number | undefined;
let resetKey = $state(0);

let isFullscreen = $state(false);
let plotScale = $state(1.0);
let aspectRatio = $state(2.0);
let showObservations = $state(true);

const COLORS = [
	"#38bdf8", "#f43f5e", "#a3e635", "#fbbf24", "#c084fc",
	"#f472b6", "#2dd4bf", "#fb923c", "#818cf8", "#e879f9"
];

let splitCol = $state<string | null>(null);
let viewMode = $state<"combined" | "subplots">("combined");
let visibleSplits = $state<Set<string>>(new Set());

// Calculate global categorical columns for the currently selected variable
let globalCategoricalCols = $derived.by(() => {
	if (!selectedVar || dataType !== "responses" || selectedIterations.length === 0) return [];

	const iter = selectedIterations[0];
	const data = parsedData[iter];
	if (!data || data.length === 0) return [];

	const subset = data.filter(r => r.response === selectedVar);
	if (subset.length === 0) return [];

	const standardCols = new Set(["realization", "response", "value"]);
	const coords = Object.keys(subset[0]).filter(k => !standardCols.has(k));

	if (coords.length >= 1) {
		let bestX = coords[0];
		let bestScore = -1;

		for (const c of coords) {
			let score = 0;
			const sample = subset[0][c];
			if (typeof sample === 'number') score = 5;
			if (typeof sample === 'string' && !isNaN(Date.parse(sample))) score = 6;
			if (c.toLowerCase().includes('time')) score = 10;
			if (c.toLowerCase().includes('step')) score = 8;

			if (score > bestScore) {
				bestScore = score;
				bestX = c;
			}
		}

		return coords.filter(c => c !== bestX);
	}
	return [];
});

$effect(() => {
	if (globalCategoricalCols.length > 0 && (!splitCol || !globalCategoricalCols.includes(splitCol))) {
		splitCol = globalCategoricalCols[0];
	} else if (globalCategoricalCols.length === 0) {
		splitCol = null;
	}
});

let globalSplitValues = $derived.by(() => {
	if (!splitCol || !selectedVar || dataType !== "responses") return [];
	const vals = new Set<string>();

	for (const iter of selectedIterations) {
		const data = parsedData[iter];
		if (data) {
			const subset = data.filter(r => r.response === selectedVar);
			subset.forEach(d => vals.add(String(d[splitCol as string])));
		}
	}
	return Array.from(vals).sort();
});

$effect(() => {
	if (globalSplitValues.length > 0) {
		const hasMissing = globalSplitValues.some(v => !visibleSplits.has(v));
		if (visibleSplits.size === 0 || (globalSplitValues.length !== visibleSplits.size && hasMissing)) {
			visibleSplits = new Set(globalSplitValues);
		}
	} else {
		visibleSplits = new Set();
	}
});

let globalColorMap = $derived.by(() => {
	const map: Record<string, string> = {};
	if (splitCol) {
		globalSplitValues.forEach((v, i) => { map[v] = COLORS[i % COLORS.length]; });
	}
	return map;
});

let globalVarType = $derived.by(() => {
	if (!selectedVar || selectedIterations.length === 0) return null;
	const iter = selectedIterations[0];
	const data = parsedData[iter];
	if (!data || data.length === 0) return null;

	if (dataType === "parameters") {
		const firstRow = data[0];
		const isArray = typeof firstRow[selectedVar] === 'object' && firstRow[selectedVar] !== null;
		return isArray ? "nd" : "1d";
	} else if (dataType === "responses") {
		const subset = data.filter(r => r.response === selectedVar);
		if (subset.length === 0) return null;

		const standardCols = new Set(["realization", "response", "value"]);
		const coords = Object.keys(subset[0]).filter(k => !standardCols.has(k));
		return coords.length >= 1 ? "timeseries" : "1d";
	}
	return null;
});

function toggleSplit(val: string) {
	const next = new Set(visibleSplits);
	if (next.has(val)) next.delete(val);
	else next.add(val);
	visibleSplits = next;
}

function toggleAllSplits() {
	if (visibleSplits.size === globalSplitValues.length) {
		visibleSplits = new Set();
	} else {
		visibleSplits = new Set(globalSplitValues);
	}
}

function triggerReset() {
	resetKey++;
	plotScale = 1.0;
	aspectRatio = 2.0;
}

// Update URL sync
$effect(() => {
	const currentParams = page.url.searchParams;
	const newUrl = new URL(page.url);
	let changed = false;

	if (currentParams.get("var") !== selectedVar) {
		if (selectedVar) newUrl.searchParams.set("var", selectedVar);
		else newUrl.searchParams.delete("var");
		changed = true;
	}

	if (currentParams.get("mode") !== plotMode) {
		newUrl.searchParams.set("mode", plotMode);
		changed = true;
	}

	if (changed) {
		goto(newUrl, { replaceState: true, keepFocus: true, noScroll: true });
	}
});

function toggleIteration(iter: number) {
	if (selectedIterations.includes(iter)) {
		if (selectedIterations.length > 1) {
			selectedIterations = selectedIterations.filter(i => i !== iter);
		}
	} else {
		selectedIterations = [...selectedIterations, iter].sort((a, b) => a - b);
	}
}

async function loadDataForIteration(iter: number, isPolling = false) {
	if (parsedData[iter] && !isPolling) return;

	if (!isPolling) {
		loading[iter] = true;
	}
	error[iter] = null;

	try {
		let fetcher = window.fetch;
		if (window.location.pathname.includes("/_app/")) {
			fetcher = (input, init) => window.fetch(new URL(input.toString(), window.location.origin), init);
		}

		const data = await fetchParquet(experimentId, executionId, iter, dataType, fetcher);
		parsedData[iter] = data;

		// If we succeed, we trigger reactivity on the entire Record
		parsedData = { ...parsedData };

		// Clear polling if all selected are loaded
		if (pollInterval && selectedIterations.every(i => parsedData[i])) {
			clearInterval(pollInterval);
			pollInterval = undefined;
		}
	} catch (e) {
		if (!pollInterval) {
			pollInterval = window.setInterval(() => {
				untrack(() => {
					selectedIterations.forEach(i => {
						if (!parsedData[i]) loadDataForIteration(i, true);
					});
				});
			}, 3000);
		}
		if (!isPolling) {
			error[iter] = e instanceof Error ? e.message : "Failed to load data";
			parsedData = { ...parsedData }; // force reactivity
		}
	} finally {
		if (!isPolling) {
			loading[iter] = false;
			loading = { ...loading };
		}
	}
}

$effect(() => {
	const iters = selectedIterations;
	untrack(() => {
		if (pollInterval) {
			clearInterval(pollInterval);
			pollInterval = undefined;
		}
		iters.forEach(iter => {
			if (!parsedData[iter]) loadDataForIteration(iter);
		});
	});
});

onDestroy(() => {
	if (pollInterval) clearInterval(pollInterval);
});

// Calculate total available columns across all loaded selected iterations
let columns = $derived.by(() => {
	const cols = new Set<string>();

	for (const iter of selectedIterations) {
		const data = parsedData[iter];
		if (!data || data.length === 0) continue;

		if (dataType === "responses") {
			if ("response" in data[0]) {
				for (const row of data) {
					if (row.response) cols.add(row.response);
				}
			}
		} else {
			Object.keys(data[0]).forEach(k => {
				if (k !== "realization") cols.add(k);
			});
		}
	}
	return Array.from(cols).sort();
});

let matchingObservations = $derived.by(() => {
	if (!observations || !selectedVar || dataType !== "responses") return [];
	return observations.filter(o => o.key.response === selectedVar);
});

// Function to build variable data for a specific iteration
function getActiveVarData(iter: number) {
	const data = parsedData[iter];
	if (!data || !selectedVar) return null;

	if (dataType === "parameters") {
		const firstRow = data[0];
		const isArray = typeof firstRow[selectedVar] === 'object' && firstRow[selectedVar] !== null;

		if (isArray) {
			const values = firstRow[selectedVar] as any[];
			return {
				type: "nd" as const,
				data: data.map(r => ({ realization: r.realization, values: Array.from(r[selectedVar as string] as any[]) })),
				entryCount: values.length,
				catCounts: {} as Record<string, number>
			};
		} else {
			return {
				type: "1d" as const,
				data: data.map(r => ({ realization: r.realization, value: Number(r[selectedVar as string]) })),
				entryCount: 1,
				catCounts: {} as Record<string, number>
			};
		}
	} else if (dataType === "responses") {
		const subset = data.filter(r => r.response === selectedVar);
		if (subset.length === 0) return null;

		const standardCols = new Set(["realization", "response", "value"]);
		const coords = Object.keys(subset[0]).filter(k => !standardCols.has(k));

		if (coords.length >= 1) {
			let bestX = coords[0];
			let bestScore = -1;

			for (const c of coords) {
				let score = 0;
				const sample = subset[0][c];
				if (typeof sample === 'number') score = 5;
				if (typeof sample === 'string' && !isNaN(Date.parse(sample))) score = 6;
				if (c.toLowerCase().includes('time')) score = 10;
				if (c.toLowerCase().includes('step')) score = 8;

				if (score > bestScore) {
					bestScore = score;
					bestX = c;
				}
			}

			const categoricalCols = coords.filter(c => c !== bestX);

			// Calculate counts
			const xPoints = new Set(subset.map(d => d[bestX]));
			const catCounts: Record<string, number> = {};
			for (const cat of categoricalCols) {
				catCounts[cat] = new Set(subset.map(d => d[cat])).size;
			}

			return {
				type: "timeseries" as const,
				xCol: bestX,
				categoricalCols,
				data: subset,
				entryCount: xPoints.size,
				catCounts
			};
		} else {
			return {
				type: "1d" as const,
				data: subset.map(r => ({ realization: r.realization, value: Number(r.value) })),
				entryCount: 1,
				catCounts: {} as Record<string, number>
			};
		}
	}
	return null;
}

let columnMetadata = $derived.by(() => {
	const meta: Record<string, { type: string, description: string, icon: string }> = {};
	if (selectedIterations.length === 0 || columns.length === 0) return meta;

	const iter = selectedIterations[0];
	const data = parsedData[iter];
	if (!data || data.length === 0) return meta;

	for (const col of columns) {
		if (dataType === "parameters") {
			const firstRow = data[0];
			const isArray = typeof firstRow[col] === 'object' && firstRow[col] !== null;

			if (isArray) {
				const values = firstRow[col] as any[];
				meta[col] = { type: "2D/3D", description: `${values.length} pts`, icon: "nd" };
			} else {
				meta[col] = { type: "1D", description: "Scalar", icon: "1d" };
			}
		} else if (dataType === "responses") {
			const subset = data.filter(r => r.response === col);
			if (subset.length === 0) continue;

			const standardCols = new Set(["realization", "response", "value"]);
			const coords = Object.keys(subset[0]).filter(k => !standardCols.has(k));

			if (coords.length >= 1) {
				let bestX = coords[0];
				let bestScore = -1;

				for (const c of coords) {
					let score = 0;
					const sample = subset[0][c];
					if (typeof sample === 'number') score = 5;
					if (typeof sample === 'string' && !isNaN(Date.parse(sample))) score = 6;
					if (c.toLowerCase().includes('time')) score = 10;
					if (c.toLowerCase().includes('step')) score = 8;

					if (score > bestScore) {
						bestScore = score;
						bestX = c;
					}
				}

				const categoricalCols = coords.filter(c => c !== bestX);
				const xPoints = new Set(subset.map(d => d[bestX]));

				let descParts = [];
				for (const cat of categoricalCols) {
					const count = new Set(subset.map(d => d[cat])).size;
					descParts.push(`${count} ${cat}`);
				}
				const ptsStr = xPoints.size === 1 ? "1 pt" : `${xPoints.size} pts`;
				descParts.push(ptsStr);

				meta[col] = { type: "Series", description: descParts.join(" | "), icon: "timeseries" };
			} else {
				meta[col] = { type: "1D", description: "Scalar", icon: "1d" };
			}
		}
	}
	return meta;
});

let globalValueRange = $derived.by(() => {
	if (!selectedVar || selectedIterations.length === 0) return undefined;
	let min = Infinity;
	let max = -Infinity;
	let hasData = false;

	for (const iter of selectedIterations) {
		const data = parsedData[iter];
		if (!data) continue;

		if (dataType === "parameters") {
			const firstRow = data[0];
			if (!firstRow) continue;
			const isArray = typeof firstRow[selectedVar] === 'object' && firstRow[selectedVar] !== null;

			for (const r of data) {
				if (isArray) {
					const arr = r[selectedVar] as number[];
					if (!arr) continue;
					for (const v of arr) {
						if (v < min) min = v;
						if (v > max) max = v;
					}
					hasData = true;
				} else {
					const v = Number(r[selectedVar]);
					if (!isNaN(v)) {
						if (v < min) min = v;
						if (v > max) max = v;
						hasData = true;
					}
				}
			}
		} else if (dataType === "responses") {
			const subset = data.filter(r => r.response === selectedVar);
			for (const r of subset) {
				const v = Number(r.value);
				if (!isNaN(v)) {
					if (v < min) min = v;
					if (v > max) max = v;
					hasData = true;
				}
			}
		}
	}

	if (!hasData || min === Infinity) return undefined;

	if (min === max) {
		min -= 1;
		max += 1;
	} else {
		// Add 5% padding
		const pad = (max - min) * 0.05;
		min -= pad;
		max += pad;
	}
	return [min, max] as [number, number];
});
</script>

<svelte:window onkeydown={(e) => { if (e.key === 'Escape' && isFullscreen) { isFullscreen = false; triggerReset(); } }} />

<div class="{isFullscreen ? '' : 'grid grid-cols-1 md:grid-cols-[250px_1fr]'} gap-4 h-full min-h-0">
	<!-- Left sidebar -->
	<div class="bg-surface-900 border border-surface-700 rounded-lg flex flex-col h-full overflow-hidden {isFullscreen ? 'hidden' : ''}">
		<header class="p-3 border-b border-surface-700 bg-surface-800 sticky top-0 flex-none">
			<h3 class="text-xs font-bold text-surface-300 uppercase tracking-wider">{dataType} Variables</h3>
		</header>
		<div class="p-2 flex flex-col gap-1 overflow-y-auto flex-auto">
			{#if selectedIterations.some(i => loading[i]) && columns.length === 0}
				<div class="p-4 text-center text-surface-500 text-xs italic flex flex-col items-center gap-2">
					<div class="w-4 h-4 border-2 border-primary-500 border-t-transparent rounded-full animate-spin"></div>
					Loading data...
				</div>
			{:else if columns.length === 0}
				<div class="p-4 text-center text-surface-500 text-xs italic">No variables found.</div>
			{:else}
				{#each columns as col}
					{@const meta = columnMetadata[col]}
					<button
						class="w-full text-left p-3 rounded-lg border transition-all duration-200 group flex flex-col gap-2 relative overflow-hidden
						       {selectedVar === col ? 'bg-surface-800 border-primary-500 shadow-[0_0_15px_rgba(14,165,233,0.15)]' : 'bg-surface-900 border-surface-700 hover:border-surface-500 hover:bg-surface-800/50'}"
						onclick={() => selectedVar = col}
					>
						{#if selectedVar === col}
							<div class="absolute inset-0 bg-gradient-to-br from-primary-500/10 to-transparent pointer-events-none"></div>
							<div class="absolute left-0 top-0 bottom-0 w-1 bg-primary-500 shadow-[0_0_10px_rgba(14,165,233,0.8)]"></div>
						{/if}

						<div class="flex items-start justify-between relative z-10 w-full">
							<span class="font-bold truncate pr-2 {selectedVar === col ? 'text-primary-400' : 'text-surface-200 group-hover:text-surface-100'}">{col}</span>
							{#if meta}
								{#if meta.icon === "nd"}
									<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 shrink-0 text-primary-500 opacity-80" fill="none" viewBox="0 0 24 24" stroke="currentColor">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4a2 2 0 012-2h12a2 2 0 012 2v12a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" />
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 12h16M12 4v16" />
									</svg>
								{:else if meta.icon === "timeseries"}
									<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 shrink-0 text-success-500 opacity-80" fill="none" viewBox="0 0 24 24" stroke="currentColor">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 12l3-3 3 3 4-4M8 21l4-4 4 4M3 4h18M4 4h16v12a1 1 0 01-1 1H5a1 1 0 01-1-1V4z" />
									</svg>
								{:else}
									<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 shrink-0 text-warning-500 opacity-80" fill="none" viewBox="0 0 24 24" stroke="currentColor">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
									</svg>
								{/if}
							{/if}
						</div>

						{#if meta}
							<div class="flex items-center gap-2 text-[10px] uppercase tracking-widest font-mono relative z-10 w-full overflow-hidden">
								<span class="px-1.5 py-0.5 rounded bg-surface-950 border border-surface-700 text-surface-400 shrink-0">{meta.type}</span>
								<span class="text-surface-500 truncate">{meta.description}</span>
							</div>
						{/if}
					</button>
				{/each}
			{/if}
		</div>
	</div>

<!-- Plot area -->
<div class="{isFullscreen ? 'fixed inset-0 z-50 bg-surface-950 p-6 shadow-2xl flex flex-col w-full h-full' : 'bg-surface-900 border border-surface-700 rounded-lg flex flex-col h-full overflow-hidden p-4 md:col-start-2'}">
	{#if !selectedVar}
			<div class="text-surface-500 italic flex flex-col items-center justify-center h-full gap-2 text-center">
				<svg xmlns="http://www.w3.org/2000/svg" class="h-12 w-12 text-surface-700" fill="none" viewBox="0 0 24 24" stroke="currentColor">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
				</svg>
				<p>Select a variable on the left to analyze.</p>
				<p class="text-xs">Data will be aggregated across all realizations.</p>
			</div>
		{:else}
			<!-- Multi-select header -->
			<header class="flex-none pb-4 border-b border-surface-700 mb-4 flex items-center justify-between">
				<div class="flex items-center gap-4 max-w-[60%]">
					<div>
						<h2 class="text-lg font-bold text-surface-200 truncate">{selectedVar}</h2>
						<p class="text-[10px] text-surface-500 uppercase tracking-widest">{dataType}</p>
					</div>

					<div class="h-8 w-px bg-surface-700 mx-2 flex-none"></div>

					<div class="flex items-center gap-2 overflow-hidden">
						<span class="text-xs font-bold text-surface-400 uppercase tracking-widest flex-none">Ensembles:</span>
						<div class="flex flex-wrap gap-1 max-h-[60px] overflow-y-auto pr-2">
							{#each Array.from({length: totalIterations}, (_, i) => i) as iter}
								<button
									class="text-[10px] font-bold px-2 py-1 rounded border transition-colors {selectedIterations.includes(iter) ? 'bg-primary-500 text-black border-primary-500' : 'bg-surface-800 text-surface-400 border-surface-700 hover:bg-surface-700'}"
									onclick={() => toggleIteration(iter)}
								>
									{iter}
								</button>
							{/each}
						</div>
					</div>
				</div>

				<div class="flex items-center gap-4">
					<div class="flex items-center gap-2">
						<span class="text-[10px] font-bold text-surface-400 uppercase tracking-widest">Scale:</span>
						<input type="range" min="0.5" max="2" step="0.1" bind:value={plotScale} class="w-16 accent-primary-500">
					</div>
					<div class="flex items-center gap-2">
						<span class="text-[10px] font-bold text-surface-400 uppercase tracking-widest">Aspect:</span>
						<input type="range" min="0.25" max="4" step="0.25" bind:value={aspectRatio} class="w-16 accent-primary-500">
					</div>
					{#if globalVarType === '1d'}
						<div class="flex bg-surface-800 rounded p-1 border border-surface-700">
							{#each ["histogram", "kde", "jitter"] as mode}
								<button
									class="px-3 py-1 text-[10px] font-bold rounded transition-colors uppercase tracking-wider {plotMode === mode ? 'bg-primary-500 text-black' : 'text-surface-400 hover:text-surface-200'}"
									onclick={() => plotMode = mode as any}
								>
									{mode}
								</button>
							{/each}
						</div>
					{/if}
					<button
						class="btn bg-surface-800 hover:bg-surface-700 text-surface-300 border border-surface-600 px-3 py-1 rounded text-xs font-bold uppercase tracking-wider transition-colors whitespace-nowrap"
						onclick={triggerReset}
						title="Reset zoom and pan"
					>
						<svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3 inline-block mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
						</svg>
						Reset
					</button>
					<button
						class="btn bg-surface-800 hover:bg-surface-700 text-surface-300 border border-surface-600 px-3 py-1 rounded text-xs font-bold uppercase tracking-wider transition-colors whitespace-nowrap"
						onclick={() => { isFullscreen = !isFullscreen; triggerReset(); }}
						title={isFullscreen ? "Exit Fullscreen" : "Fullscreen Plot Area"}
					>
						<svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3 inline-block mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
							{#if isFullscreen}
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
							{:else}
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
							{/if}
						</svg>
						{isFullscreen ? 'Exit' : 'Expand'}
					</button>

					{#if observations.length > 0}
						<div class="flex items-center gap-2 ml-auto">
							<label class="flex items-center gap-2 text-[10px] font-bold text-surface-400 uppercase tracking-widest cursor-pointer">
								<input type="checkbox" bind:checked={showObservations} class="accent-primary-500 w-3 h-3 bg-surface-800 border-surface-600 rounded">
								Show Observations
							</label>
						</div>
					{/if}
				</div>
			</header>

			{#if globalCategoricalCols.length > 0}
				<header class="flex-none p-3 bg-surface-900 border-b border-surface-700 mb-4 flex flex-col gap-3 rounded">
					<div class="flex items-center gap-4">
						<div class="flex items-center gap-2">
							<span class="text-xs font-bold text-surface-400 uppercase tracking-widest">Split By:</span>
							<select
								bind:value={splitCol}
								class="bg-surface-800 border border-surface-600 text-surface-200 text-xs rounded px-2 py-1 focus:outline-none focus:border-primary-500"
							>
								{#each globalCategoricalCols as c}
									<option value={c}>{c}</option>
								{/each}
							</select>
						</div>

						<div class="flex items-center gap-2">
							<span class="text-xs font-bold text-surface-400 uppercase tracking-widest">View:</span>
							<div class="flex bg-surface-800 rounded p-0.5 border border-surface-600">
								<button
									class="px-2 py-1 text-[10px] font-bold rounded uppercase {viewMode === 'combined' ? 'bg-primary-500 text-black' : 'text-surface-400 hover:text-surface-200'}"
									onclick={() => viewMode = 'combined'}
								>
									Combined
								</button>
								<button
									class="px-2 py-1 text-[10px] font-bold rounded uppercase {viewMode === 'subplots' ? 'bg-primary-500 text-black' : 'text-surface-400 hover:text-surface-200'}"
									onclick={() => viewMode = 'subplots'}
								>
									Subplots
								</button>
							</div>
						</div>
					</div>

					<!-- Filter Pills acting as Global Legend -->
					{#if splitCol}
						<div class="flex flex-wrap gap-2 items-center">
							<button
								class="text-[10px] font-bold px-2 py-1 rounded border {visibleSplits.size === globalSplitValues.length ? 'bg-surface-700 text-surface-200 border-surface-500' : 'bg-surface-800 text-surface-400 border-surface-700 hover:bg-surface-700'}"
								onclick={toggleAllSplits}
							>
								ALL
							</button>
							<div class="w-px h-4 bg-surface-700"></div>
							{#each globalSplitValues as val}
								<button
									class="text-[10px] font-bold px-2 py-1 rounded border transition-colors flex items-center gap-1.5"
									style="
										background-color: {visibleSplits.has(val) ? globalColorMap[val] + '33' : 'transparent'};
										border-color: {visibleSplits.has(val) ? globalColorMap[val] : 'var(--color-surface-700)'};
										color: {visibleSplits.has(val) ? globalColorMap[val] : 'var(--color-surface-500)'};
									"
									onclick={() => toggleSplit(val)}
								>
									<div class="w-2 h-2 rounded-full" style="background-color: {globalColorMap[val]}; opacity: {visibleSplits.has(val) ? 1 : 0.3};"></div>
									{val}
								</button>
							{/each}
						</div>
					{/if}
				</header>
			{/if}

			<div class="flex-auto relative min-h-0 overflow-y-auto">
				<div class="flex flex-row flex-wrap gap-2 items-start pb-4 w-full">
					{#each selectedIterations as iter}
						{@const activeVarData = getActiveVarData(iter)}

						{#if loading[iter] && !parsedData[iter]}
							<div class="w-[300px] bg-surface-950 border border-surface-800 rounded flex flex-col items-center justify-center text-surface-500 italic text-xs" style="height: {300/aspectRatio}px;">
								<div class="w-4 h-4 border-2 border-primary-500 border-t-transparent rounded-full animate-spin mb-2"></div>
								Loading Iter {iter}...
							</div>
						{:else if error[iter]}
							<div class="w-[300px] bg-error-500/10 border border-error-500/50 rounded flex items-center justify-center text-error-400 text-xs p-4 text-center" style="height: {300/aspectRatio}px;">
								{error[iter]}
							</div>
						{:else if !activeVarData}
							<div class="w-[300px] bg-surface-950 border border-surface-800 rounded flex items-center justify-center text-surface-500 italic text-xs" style="height: {300/aspectRatio}px;">
								No data for Iter {iter}
							</div>
						{:else}
							<div class="flex-none p-1">
								<div class="inline-block bg-surface-950 border border-surface-800 rounded shadow-lg overflow-hidden">
									{#key resetKey + '_' + plotScale + '_' + aspectRatio}
										{#if activeVarData.type === 'nd'}
											<div class="relative">
												<div class="absolute top-1 left-2 z-10 text-[10px] font-bold text-surface-400 bg-surface-900/80 px-1 rounded uppercase tracking-tighter">
													{selectedVar} - Iter {iter}
												</div>
												<div style="width: {Math.round(plotScale * Math.sqrt(320000 * aspectRatio))}px; height: {Math.round(plotScale * Math.sqrt(320000 / aspectRatio))}px;">
													<DeckGLPlot data={activeVarData.data as any[]} valueRange={globalValueRange} />
												</div>
											</div>
										{:else if activeVarData.type === '1d'}
											<DistributionPlot
												data={activeVarData.data as any[]}
												mode={plotMode}
												observations={matchingObservations}
												scale={plotScale}
												aspectRatio={aspectRatio}
												showObservations={showObservations}
												title={`${selectedVar} - Iter ${iter}`}
												valueRange={globalValueRange}
											/>
										{:else if activeVarData.type === 'timeseries'}
											<TimeSeriesPlot
												data={activeVarData.data as any[]}
												xCol={activeVarData.xCol as string}
												categoricalCols={activeVarData.categoricalCols}
												observations={matchingObservations}
												scale={plotScale}
												aspectRatio={aspectRatio}
												viewMode={viewMode}
												splitCol={splitCol}
												visibleSplits={visibleSplits}
												splitValues={globalSplitValues}
												colorMap={globalColorMap}
												showObservations={showObservations}
												iterationTitle={`${selectedVar} - Iter ${iter}`}
												yRange={globalValueRange}
											/>
										{/if}
									{/key}
								</div>
							</div>
						{/if}
					{/each}
				</div>
			</div>
		{/if}
	</div>
</div>
