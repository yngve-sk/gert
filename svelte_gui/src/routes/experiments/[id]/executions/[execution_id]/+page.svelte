<script lang="ts">
import { onDestroy, onMount } from "svelte";
import { page } from "$app/state";
import { pauseExecution, resumeExecution } from "$lib/api/client";
import IterationDashboard from "$lib/components/dashboard/IterationDashboard.svelte";
import SpatialContainer from "$lib/components/plotting/SpatialContainer.svelte";
import VirtualizedTerminal from "$lib/components/VirtualizedTerminal.svelte";
import { ExecutionWebSocketStore } from "$lib/stores/websocket.svelte";
import type { PageData } from "./$types";

// biome-ignore lint/correctness/noUnusedVariables: used in render
let { data }: { data: PageData } = $props();

let wsStore: ExecutionWebSocketStore | null = $state(null);
let isActionPending = $state(false);
let actionError = $state<string | null>(null);

let activeTab = $state<"console" | "responses" | "observations" | "parameters" | "spatial">("console");

onMount(() => {
	const experimentId = data.experimentId;
	const executionId = data.executionId;
	wsStore = new ExecutionWebSocketStore(
		experimentId,
		executionId,
		data.initialStatus,
	);
	wsStore.connect();
});

onDestroy(() => {
	if (wsStore) {
		wsStore.disconnect();
	}
});

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

let totalIterations = $derived(data.config?.updates ? data.config.updates.length + 1 : 1);
</script>

<div class="flex flex-col gap-4 max-w-7xl h-full w-full">
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

		<div class="flex items-center gap-4">
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

	<div class="grid grid-cols-1 lg:grid-cols-[350px_1fr] gap-4 h-[calc(100vh-140px)] w-full">
		<!-- Left Sidebar: Iteration Dashboard -->
		<section class="bg-surface-800 border border-surface-700 rounded-lg p-4 shadow-lg flex flex-col h-full overflow-hidden">
			<IterationDashboard events={wsStore?.statusEvents || []} totalIterations={totalIterations} />
		</section>

		<!-- Right Content: Multi-tab workspace -->
		<section class="bg-surface-800 border border-surface-700 rounded-lg shadow-lg flex flex-col h-full overflow-hidden min-w-0">
			<header class="flex border-b border-surface-700 bg-surface-900 overflow-x-auto">
				<button
					class="px-4 py-2 text-sm font-bold border-b-2 whitespace-nowrap transition-colors {activeTab === 'console' ? 'border-primary-500 text-primary-500' : 'border-transparent text-surface-400 hover:text-surface-200 hover:bg-surface-800'}"
					onclick={() => activeTab = 'console'}
				>
					Console
				</button>
				<button
					class="px-4 py-2 text-sm font-bold border-b-2 whitespace-nowrap transition-colors {activeTab === 'responses' ? 'border-primary-500 text-primary-500' : 'border-transparent text-surface-400 hover:text-surface-200 hover:bg-surface-800'}"
					onclick={() => activeTab = 'responses'}
				>
					Responses Dashboard
				</button>
				<button
					class="px-4 py-2 text-sm font-bold border-b-2 whitespace-nowrap transition-colors {activeTab === 'observations' ? 'border-primary-500 text-primary-500' : 'border-transparent text-surface-400 hover:text-surface-200 hover:bg-surface-800'}"
					onclick={() => activeTab = 'observations'}
				>
					Observations Dashboard
				</button>
				<button
					class="px-4 py-2 text-sm font-bold border-b-2 whitespace-nowrap transition-colors {activeTab === 'parameters' ? 'border-primary-500 text-primary-500' : 'border-transparent text-surface-400 hover:text-surface-200 hover:bg-surface-800'}"
					onclick={() => activeTab = 'parameters'}
				>
					Parameters Dashboard
				</button>
				<button
					class="px-4 py-2 text-sm font-bold border-b-2 whitespace-nowrap transition-colors {activeTab === 'spatial' ? 'border-primary-500 text-primary-500' : 'border-transparent text-surface-400 hover:text-surface-200 hover:bg-surface-800'}"
					onclick={() => activeTab = 'spatial'}
				>
					Spatial Field
				</button>
			</header>

			<div class="flex-auto overflow-hidden relative p-4">
				{#if activeTab === 'console'}
					<VirtualizedTerminal
						experimentId={data.experimentId}
						executionId={data.executionId}
						isRunning={data.execution?.status === 'RUNNING' || data.execution?.status === 'PAUSED'}
					/>
				{:else if activeTab === 'spatial'}
					<SpatialContainer />
				{:else if activeTab === 'responses' || activeTab === 'observations' || activeTab === 'parameters'}
					<div class="grid grid-cols-1 md:grid-cols-[250px_1fr] gap-4 h-full">
						<!-- List of items to select -->
						<div class="bg-surface-900 border border-surface-700 rounded-lg overflow-y-auto flex flex-col">
							<header class="p-2 border-b border-surface-700 bg-surface-800 sticky top-0">
								<h3 class="text-xs font-bold text-surface-300 uppercase tracking-wider">{activeTab} List</h3>
							</header>
							<div class="p-2 flex flex-col gap-1">
								{#each [1, 2, 3, 4, 5] as i}
									<button class="text-left px-3 py-2 text-sm text-surface-200 hover:bg-surface-700 rounded transition-colors focus:bg-surface-700 border border-transparent focus:border-surface-600 focus:outline-none">
										Sample {activeTab.slice(0, -1)} {i}
									</button>
								{/each}
							</div>
						</div>

						<!-- Plot Area -->
						<div class="h-full w-full flex items-center justify-center border border-dashed border-surface-700 rounded-lg bg-surface-900/50">
							<div class="text-center">
								<svg xmlns="http://www.w3.org/2000/svg" class="h-12 w-12 mx-auto text-surface-600 mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 12l3-3 3 3 4-4M8 21l4-4 4 4M3 4h18M4 4h16v12a1 1 0 01-1 1H5a1 1 0 01-1-1V4z" />
								</svg>
								<p class="text-surface-300 font-bold mb-1">Plot Area</p>
								<p class="text-surface-500 text-sm">Select an item from the list to display its data.</p>
							</div>
						</div>
					</div>
				{/if}
			</div>
		</section>
	</div>
</div>
