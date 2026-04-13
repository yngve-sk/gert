<script lang="ts">
import { onMount, untrack, onDestroy } from "svelte";
import { getUpdateMetadata, type UpdateMetadata } from "$lib/api/client";

interface Props {
	experimentId: string;
	executionId: string;
	iteration: number | null;
}

let { experimentId, executionId, iteration }: Props = $props();

let metadata: UpdateMetadata | null = $state(null);
let loading = $state(false);
let error = $state<string | null>(null);
let pollInterval: number | undefined;

function startPolling(iter: number) {
	if (pollInterval) clearInterval(pollInterval);

	pollInterval = window.setInterval(async () => {
		try {
			const meta = await getUpdateMetadata(experimentId, executionId, iter + 1);
			metadata = meta;
			error = null;
			if (meta.status === "COMPLETED" || meta.status === "FAILED") {
				clearInterval(pollInterval);
				pollInterval = undefined;
			}
		} catch (e) {
			// still waiting, keep polling
		}
	}, 3000);
}

async function fetchMetadata(iter: number) {
	loading = true;
	error = null;
	if (pollInterval) clearInterval(pollInterval);

	try {
		// The update "iter" produces ensemble "iter + 1", so the metadata lives there
		metadata = await getUpdateMetadata(experimentId, executionId, iter + 1);
		if (metadata.status === "RUNNING") {
			startPolling(iter);
		}
	} catch (e) {
		error = e instanceof Error ? e.message : "Failed to load update metadata";
		metadata = null;
		// If it's a 404, it hasn't started/finished writing yet.
		startPolling(iter);
	} finally {
		loading = false;
	}
}

$effect(() => {
	const currentIter = iteration;
	untrack(() => {
		if (currentIter !== null) {
			fetchMetadata(currentIter);
		} else {
			if (pollInterval) clearInterval(pollInterval);
			metadata = null;
		}
	});
});

onDestroy(() => {
	if (pollInterval) clearInterval(pollInterval);
});

function formatDuration(seconds: number | null | undefined): string {
	if (seconds === null || seconds === undefined) return "N/A";
	if (seconds < 1) return `${(seconds * 1000).toFixed(0)} ms`;
	if (seconds < 60) return `${seconds.toFixed(2)} s`;
	return `${(seconds / 60).toFixed(2)} min`;
}

function formatMisfit(val: any): string {
	if (typeof val === 'number') {
		return Number(val.toFixed(4)).toString();
	}
	return String(val);
}

// Process metrics into prior -> posterior groups where possible
let groupedMetrics = $derived.by(() => {
	if (!metadata || !metadata.metrics) return [];

	const groups = new Map<string, { prior?: any, posterior?: any, single?: any }>();

	for (const [key, value] of Object.entries(metadata.metrics)) {
		let baseKey = key;
		if (key.startsWith('prior_')) {
			baseKey = key.substring(6);
			const entry = groups.get(baseKey) || {};
			entry.prior = value;
			groups.set(baseKey, entry);
		} else if (key.startsWith('posterior_')) {
			baseKey = key.substring(10);
			const entry = groups.get(baseKey) || {};
			entry.posterior = value;
			groups.set(baseKey, entry);
		} else {
			const entry = groups.get(baseKey) || {};
			entry.single = value;
			groups.set(baseKey, entry);
		}
	}

	return Array.from(groups.entries()).map(([baseKey, vals]) => {
		const label = baseKey.replace(/_/g, ' ');
		if (vals.prior !== undefined || vals.posterior !== undefined) {
			const hasBoth = typeof vals.prior === 'number' && typeof vals.posterior === 'number';
			const diff = hasBoth ? (vals.posterior - vals.prior) : null;
			return {
				label,
				isPair: true,
				prior: vals.prior,
				posterior: vals.posterior,
				diff,
				baseKey
			};
		}
		return { label, isPair: false, text: formatMisfit(vals.single), baseKey, singleValue: vals.single };
	});
});

let daStats = $derived.by(() => {
	if (!metadata || !metadata.metrics) return null;
	const m = metadata.metrics;

	// Fuzzy matching for standard DA metrics
	const getVal = (searchStrs: string[]) => {
		for (const key of Object.keys(m)) {
			const lowerKey = key.toLowerCase();
			if (searchStrs.some(s => lowerKey.includes(s))) return Number(m[key]);
		}
		return null;
	};

	const updatedParams = getVal(['num_updated_param', 'active_param', 'updated_parameters']);
	const notUpdatedParams = getVal(['num_inactive_param', 'inactive_param', 'not_updated']);
	const discardedObs = getVal(['discarded_obs', 'num_discarded']);
	const totalObs = getVal(['total_obs', 'num_observations', 'num_obs']);

	if (updatedParams === null && discardedObs === null) return null;

	const allDiscarded = discardedObs !== null && totalObs !== null && discardedObs >= totalObs;

	return {
		updatedParams,
		notUpdatedParams,
		discardedObs,
		totalObs,
		allDiscarded
	};
});
</script>

<div class="h-full w-full bg-surface-900 overflow-y-auto p-4 flex flex-col gap-3">
	{#if iteration === null}
		<div class="flex-auto flex flex-col items-center justify-center text-surface-500 text-sm italic">
			<svg xmlns="http://www.w3.org/2000/svg" class="h-12 w-12 mb-4 text-surface-700" fill="none" viewBox="0 0 24 24" stroke="currentColor">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
			</svg>
			Please select an Update from the Ensembles Dashboard.
		</div>
	{:else if loading}
		<div class="flex-auto flex flex-col items-center justify-center text-surface-400 text-sm">
			<div class="w-6 h-6 border-2 border-primary-500 border-t-transparent rounded-full animate-spin mb-4"></div>
			Loading update metadata...
		</div>
	{:else if error}
		<div class="flex-auto flex items-center justify-center">
			<aside class="bg-error-500/10 border border-error-500/50 rounded-lg p-4 max-w-lg w-full text-center">
				<h3 class="text-error-500 font-bold text-sm">Error Loading Metadata</h3>
				<p class="text-xs text-error-400 mt-2">{error}</p>
				<p class="text-xs text-surface-500 mt-4 italic">The update might not be finished or started yet.</p>
			</aside>
		</div>
	{:else if metadata}
		<header class="flex justify-between items-center pb-3 border-b border-surface-700">
			<div>
				<h2 class="text-lg font-bold text-tertiary-400 flex items-center gap-2">
					<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
						<path fill-rule="evenodd" d="M11.49 3.17c-.38-1.56-2.6-1.56-2.98 0a1.532 1.532 0 01-2.286.948c-1.372-.836-2.942.734-2.106 2.106.54.886.061 2.042-.947 2.287-1.561.379-1.561 2.6 0 2.978a1.532 1.532 0 01.947 2.287c-.836 1.372.734 2.942 2.106 2.106a1.532 1.532 0 012.287.947c.379 1.561 2.6 1.561 2.978 0a1.533 1.533 0 012.287-.947c1.372.836 2.942-.734 2.106-2.106a1.533 1.533 0 01.947-2.287c1.561-.379 1.561-2.6 0-2.978a1.532 1.532 0 01-.947-2.287c.836-1.372-.734-2.942-2.106-2.106a1.532 1.532 0 01-2.287-.947zM10 13a3 3 0 100-6 3 3 0 000 6z" clip-rule="evenodd" />
					</svg>
					Update {iteration} Info
				</h2>
				<p class="text-xs text-surface-400 mt-1 font-mono">{metadata.algorithm_name}</p>
			</div>
			<div class="text-right">
				<span class="badge {metadata.status === 'COMPLETED' ? 'bg-success-500/20 text-success-400 border border-success-500/30' : metadata.status === 'FAILED' ? 'bg-error-500/20 text-error-400 border border-error-500/30' : 'bg-surface-800 text-surface-400'} px-2 py-1 rounded text-xs font-bold tracking-widest">
					{metadata.status}
				</span>
			</div>
		</header>

		<div class="grid grid-cols-1 md:grid-cols-2 gap-4">
			<!-- Execution Metrics -->
			<section class="bg-surface-800 border border-surface-700 rounded p-3">
				<h3 class="text-xs font-bold uppercase tracking-widest text-surface-400 mb-3 pb-1 border-b border-surface-700/50">Execution Metrics</h3>
				<div class="space-y-2 text-sm">
					<div class="flex justify-between">
						<span class="text-surface-300">Duration</span>
						<span class="font-mono text-tertiary-400 font-bold">{formatDuration(metadata.duration_seconds)}</span>
					</div>
					<div class="flex justify-between">
						<span class="text-surface-300">Start Time</span>
						<span class="font-mono text-surface-400 text-xs">{metadata.start_time ? new Date(metadata.start_time).toLocaleString() : 'N/A'}</span>
					</div>
					<div class="flex justify-between">
						<span class="text-surface-300">End Time</span>
						<span class="font-mono text-surface-400 text-xs">{metadata.end_time ? new Date(metadata.end_time).toLocaleString() : 'N/A'}</span>
					</div>
				</div>
			</section>

			<!-- DA Constraints & Warnings -->
			{#if daStats}
				<section class="bg-surface-800 border {daStats.allDiscarded ? 'border-error-500/50 bg-error-500/10' : 'border-surface-700'} rounded p-3">
					<h3 class="text-xs font-bold uppercase tracking-widest {daStats.allDiscarded ? 'text-error-400' : 'text-surface-400'} mb-3 pb-1 border-b border-surface-700/50 flex items-center justify-between">
						Assimilation Diagnostics
						{#if daStats.allDiscarded}
							<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-error-500 animate-pulse" fill="none" viewBox="0 0 24 24" stroke="currentColor">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
							</svg>
						{/if}
					</h3>

					{#if daStats.allDiscarded}
						<div class="text-xs font-bold text-error-500 mb-3 bg-error-500/20 px-2 py-1 rounded border border-error-500/30">
							WARNING: ALL OBSERVATIONS WERE DISCARDED. NO UPDATE WAS PERFORMED!
						</div>
					{/if}

					<div class="grid grid-cols-2 gap-2 text-sm">
						{#if daStats.updatedParams !== null}
							<div class="flex flex-col bg-surface-900 border border-surface-700/50 p-2 rounded">
								<span class="text-[10px] uppercase text-surface-500 font-bold">Updated Params</span>
								<span class="font-mono text-primary-400">{daStats.updatedParams}</span>
							</div>
						{/if}
						{#if daStats.notUpdatedParams !== null}
							<div class="flex flex-col bg-surface-900 border border-surface-700/50 p-2 rounded">
								<span class="text-[10px] uppercase text-surface-500 font-bold">Inactive Params</span>
								<span class="font-mono text-warning-400">{daStats.notUpdatedParams}</span>
							</div>
						{/if}
						{#if daStats.discardedObs !== null}
							<div class="flex flex-col bg-surface-900 border border-surface-700/50 p-2 rounded">
								<span class="text-[10px] uppercase text-surface-500 font-bold">Discarded Obs</span>
								<span class="font-mono {daStats.discardedObs > 0 ? 'text-error-400' : 'text-success-400'}">
									{daStats.discardedObs} {#if daStats.totalObs !== null}/ {daStats.totalObs}{/if}
								</span>
							</div>
						{/if}
					</div>
				</section>
			{/if}

			<!-- Mathematical Metrics -->
			<section class="bg-surface-800 border border-surface-700 rounded p-3 {daStats ? 'md:col-span-2' : ''}">				<h3 class="text-xs font-bold uppercase tracking-widest text-surface-400 mb-3 pb-1 border-b border-surface-700/50">Algorithm Metrics</h3>
				<div class="space-y-2 text-sm">
					{#if groupedMetrics.length === 0}
						<div class="text-surface-500 italic text-xs">No metrics recorded.</div>
					{:else}
						{#each groupedMetrics as metric}
							<div class="flex justify-between items-center py-1.5 border-b border-surface-700/30 last:border-0 last:pb-0">
								<span class="text-surface-300 capitalize text-sm">{metric.label}</span>
								{#if metric.isPair}
									{#if metric.diff !== null && metric.diff !== undefined}
										<div class="flex items-center gap-3">
											<div class="flex items-center gap-1 font-mono font-bold text-sm {metric.diff > 0 ? 'text-error-500' : (metric.diff < 0 ? 'text-success-500' : 'text-surface-400')}">
												{#if metric.diff > 0}
													<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
														<path fill-rule="evenodd" d="M14.707 12.707a1 1 0 01-1.414 0L10 9.414l-3.293 3.293a1 1 0 01-1.414-1.414l4-4a1 1 0 011.414 0l4 4a1 1 0 010 1.414z" clip-rule="evenodd" />
													</svg>
												{:else if metric.diff < 0}
													<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
														<path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd" />
													</svg>
												{/if}
												<span>({metric.diff > 0 ? '+' : ''}{formatMisfit(metric.diff)})</span>
											</div>
											<span class="font-mono text-[11px] text-surface-500 whitespace-nowrap bg-surface-900/50 px-2 py-0.5 rounded border border-surface-700/50">
												{formatMisfit(metric.prior)} → {formatMisfit(metric.posterior)}
											</span>
										</div>
									{:else}
										<span class="font-mono text-surface-500 italic text-xs">(pending)</span>
									{/if}
								{:else}
									<span class="font-mono text-primary-400 text-sm">{metric.text}</span>
								{/if}
							</div>
						{/each}
					{/if}
				</div>
			</section>

			<!-- Configuration -->
			{#if Object.keys(metadata.configuration).length > 0}
				<section class="bg-surface-800 border border-surface-700 rounded p-3 md:col-span-2">
					<h3 class="text-xs font-bold uppercase tracking-widest text-surface-400 mb-3 pb-1 border-b border-surface-700/50">Configuration</h3>
					<div class="grid grid-cols-2 lg:grid-cols-4 gap-4 text-xs">
						{#each Object.entries(metadata.configuration) as [key, value]}
							<div class="flex flex-col">
								<span class="text-surface-500 mb-0.5 font-mono">{key}</span>
								<span class="font-bold text-surface-200 bg-surface-900 px-2 py-1 rounded border border-surface-700/50">{value}</span>
							</div>
						{/each}
					</div>
				</section>
			{/if}
		</div>
	{/if}
</div>
