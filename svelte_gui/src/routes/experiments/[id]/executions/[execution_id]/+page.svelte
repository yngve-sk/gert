<script lang="ts">
import { onDestroy, onMount } from "svelte";
import { page } from "$app/state";
import { pauseExecution, resumeExecution } from "$lib/api/client";
// biome-ignore lint/correctness/noUnusedImports: used in HTML template
import IterationDashboard from "$lib/components/dashboard/IterationDashboard.svelte";
// biome-ignore lint/correctness/noUnusedImports: used in HTML template
import SpatialContainer from "$lib/components/plotting/SpatialContainer.svelte";
// biome-ignore lint/correctness/noUnusedImports: used in HTML template
import VirtualizedTerminal from "$lib/components/VirtualizedTerminal.svelte";
import { ExecutionWebSocketStore } from "$lib/stores/websocket.svelte";

let wsStore: ExecutionWebSocketStore | null = $state(null);

// biome-ignore lint/correctness/noUnusedVariables: used in HTML template bindings
let isActionPending = $state(false);
// biome-ignore lint/correctness/noUnusedVariables: used in HTML template bindings
let actionError = $state<string | null>(null);

onMount(() => {
	const experimentId = page.params.id || "";
	const executionId = page.params.execution_id || "";
	wsStore = new ExecutionWebSocketStore(experimentId, executionId);
	wsStore.connect();
});

onDestroy(() => {
	if (wsStore) {
		wsStore.disconnect();
	}
});

// biome-ignore lint/correctness/noUnusedVariables: used in HTML template bindings
async function handlePause() {
	if (!page.params.id || !page.params.execution_id) return;
	isActionPending = true;
	actionError = null;
	try {
		await pauseExecution(page.params.id, page.params.execution_id);
	} catch (e) {
		actionError = e instanceof Error ? e.message : "Failed to pause";
	} finally {
		isActionPending = false;
	}
}

// biome-ignore lint/correctness/noUnusedVariables: used in HTML template bindings
async function handleResume() {
	if (!page.params.id || !page.params.execution_id) return;
	isActionPending = true;
	actionError = null;
	try {
		await resumeExecution(page.params.id, page.params.execution_id);
	} catch (e) {
		actionError = e instanceof Error ? e.message : "Failed to resume";
	} finally {
		isActionPending = false;
	}
}
</script>

<div class="flex flex-col gap-4 max-w-5xl h-full">
	<header class="flex items-center justify-between border-b border-surface-800 bg-surface-900 px-4 py-3 rounded-t-lg shadow-sm">
		<div class="flex items-center gap-4">
			<a href="/experiments/{page.params.id}" class="btn bg-surface-800 hover:bg-surface-700 text-surface-300 px-3 py-1.5 rounded border border-surface-700 text-sm transition-colors">
				&larr; Back
			</a>
			<div>
				<h1 class="text-xl font-bold tracking-tight text-surface-50">Execution Inspector</h1>
				<p class="text-xs font-mono text-surface-400 mt-1">{page.params.execution_id}</p>
			</div>
		</div>

		<!-- Execution Controls (M8) & Pulse (M7) -->
		<div class="flex items-center gap-4">
			<!-- M8 Execution Control Action Buttons -->
			<div class="flex items-center gap-2 bg-surface-950 p-1 rounded border border-surface-800">
				<button
					class="btn bg-tertiary-500 hover:bg-tertiary-400 text-white px-3 py-1 text-xs font-bold rounded transition-colors disabled:opacity-50"
					onclick={handlePause}
					disabled={isActionPending}
				>
					Pause
				</button>
				<button
					class="btn bg-primary-500 hover:bg-primary-400 text-white px-3 py-1 text-xs font-bold rounded transition-colors disabled:opacity-50"
					onclick={handleResume}
					disabled={isActionPending}
				>
					Resume
				</button>
			</div>

			<!-- M7 WebSocket Pulse Indicator -->
			{#if wsStore}
				<div class="flex items-center gap-2 px-3 py-1.5 rounded-full bg-surface-800 border {wsStore.isConnected ? 'border-success-500/50' : 'border-error-500/50'}">
					<div class="w-2 h-2 rounded-full {wsStore.isConnected ? 'bg-success-500 animate-pulse' : 'bg-error-500'}"></div>
					<span class="text-xs font-bold {wsStore.isConnected ? 'text-success-500' : 'text-error-500'}">
						{wsStore.isConnected ? 'LIVE' : 'DISCONNECTED'}
					</span>
				</div>
			{/if}
		</div>
	</header>

	{#if wsStore?.error || actionError}
		<aside class="bg-error-500/10 border border-error-500/50 rounded-lg p-3">
			{#if wsStore?.error}
				<p class="text-xs text-error-400">WebSocket: {wsStore.error}</p>
			{/if}
			{#if actionError}
				<p class="text-xs text-error-400">Action: {actionError}</p>
			{/if}
		</aside>
	{/if}

	<div class="grid grid-cols-1 xl:grid-cols-2 gap-4 h-full">
		<section class="bg-surface-800 border border-surface-700 rounded-lg p-4 shadow-lg flex flex-col h-full min-h-[400px] overflow-hidden">
			<!-- M9 Iteration Dashboard -->
			<IterationDashboard events={wsStore?.statusEvents || []} />
		</section>

		<!-- M11 Spatial Analysis -->
		<section class="bg-surface-800 border border-surface-700 rounded-lg p-4 shadow-lg flex flex-col h-full min-h-[400px] overflow-hidden">
			<h2 class="text-sm font-bold text-surface-100 mb-2 border-b border-surface-700 pb-2">Spatial Field</h2>
			<div class="flex-auto overflow-hidden rounded relative">
				<SpatialContainer />
			</div>
		</section>

		<!-- M8 Virtualized Terminal (spanning full width) -->
		<section class="bg-surface-800 border border-surface-700 rounded-lg p-4 shadow-lg flex flex-col h-full min-h-[400px] overflow-hidden xl:col-span-2">
			<h2 class="text-sm font-bold text-surface-100 mb-2 border-b border-surface-700 pb-2">Console</h2>
			<div class="flex-auto overflow-hidden rounded relative">
				<VirtualizedTerminal />
			</div>
		</section>
	</div>
</div>
