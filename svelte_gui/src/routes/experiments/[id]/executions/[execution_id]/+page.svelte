<script lang="ts">
import { onDestroy, onMount } from "svelte";
import { page } from "$app/state";
import { pauseExecution, resumeExecution } from "$lib/api/client";
import EnsemblesSidebar from "$lib/components/dashboard/EnsemblesSidebar.svelte";
import ExperimentSummaryTab from "$lib/components/dashboard/ExperimentSummaryTab.svelte";
import RealizationStatusTab from "$lib/components/dashboard/RealizationStatusTab.svelte";
import AnalysisDashboard from "$lib/components/dashboard/AnalysisDashboard.svelte";
import UpdateInfoTab from "$lib/components/dashboard/UpdateInfoTab.svelte";
import SpatialContainer from "$lib/components/plotting/SpatialContainer.svelte";
import VirtualizedTerminal from "$lib/components/VirtualizedTerminal.svelte";
import { ExecutionWebSocketStore } from "$lib/stores/websocket.svelte";
import type { PageData } from "./$types";

// biome-ignore lint/correctness/noUnusedVariables: used in render
let { data }: { data: PageData } = $props();

let wsStore: ExecutionWebSocketStore | null = $state(null);
let isActionPending = $state(false);
let actionError = $state<string | null>(null);

let activeTab = $state<"console" | "realizations" | "updates" | "responses" | "observations" | "parameters">("updates");

let selectedIteration = $state<number | null>(null);
let selectedRealization = $state<number | null>(null);
let selectedUpdate = $state<number | null>(null);

function handleSelectOverview() {
	selectedIteration = null;
	selectedRealization = null;
	selectedUpdate = null;
	if (activeTab !== "updates") {
		activeTab = "updates";
	}
}

function handleSelectIteration(iter: number | null) {
	selectedIteration = iter;
	if (iter !== null) {
		selectedUpdate = null;
	}
}

function handleSelectRealization(realizationId: number | null) {
	selectedRealization = realizationId;
	if (realizationId !== null) {
		if (activeTab !== "realizations") {
			activeTab = "realizations";
		}
	}
}

function handleSelectUpdate(iter: number | null) {
	selectedUpdate = iter;
	if (iter !== null) {
		selectedIteration = null;
		selectedRealization = null;
		if (activeTab !== "updates") {
			activeTab = "updates";
		}
	}
}

let currentStatus = $derived.by(() => {
	// Look for overarching status (-1, -1) in WS events, fallback to static page data
	const overarching = wsStore?.statusEvents.find(e => e.realization_id === -1 && e.iteration === -1);
	return overarching ? overarching.status : (data.execution?.status || "PENDING");
});

let isFinished = $derived(
	currentStatus === "COMPLETED" ||
	currentStatus === "FAILED" ||
	currentStatus === "CANCELED"
);

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

async function handlePause(force = false) {
	if (!data.experimentId || !data.executionId) return;
	isActionPending = true;
	actionError = null;
	try {
		await pauseExecution(data.experimentId, data.executionId, window.fetch, force);
	} catch (e) {
		actionError = e instanceof Error ? e.message : "Failed to pause";
	} finally {
		isActionPending = false;
	}
}

async function handleResume() {
	if (!data.experimentId || !data.executionId) return;
	isActionPending = true;
	actionError = null;
	try {
		await resumeExecution(data.experimentId, data.executionId, window.fetch);
	} catch (e) {
		actionError = e instanceof Error ? e.message : "Failed to resume";
	} finally {
		isActionPending = false;
	}
}

let totalIterations = $derived(data.config?.updates ? data.config.updates.length + 1 : 1);
let numSteps = $derived(data.config?.forward_model_steps ? data.config.forward_model_steps.length : 1);
</script>

<div class="flex flex-col gap-4 h-full w-full">
	<header class="flex items-center justify-between border-b border-surface-800 bg-surface-900 px-4 py-3 rounded-t-lg shadow-sm">
		<div class="flex items-center gap-4">
			<a href="/experiments/{data.experimentId}" class="btn bg-surface-800 hover:bg-surface-700 text-surface-300 px-3 py-1.5 rounded border border-surface-700 text-sm transition-colors">
				&larr; Back
			</a>
			<div>
				<h1 class="text-xl font-bold tracking-tight text-surface-50">Execution Inspector</h1>
				<p class="text-xs font-mono text-surface-400 mt-1">{data.executionId}</p>
			</div>
		</div>

		<div class="flex items-center gap-4">
			{#if !isFinished}
				<div class="flex items-center gap-2 bg-surface-950 p-1 rounded border border-surface-800">
					{#if currentStatus === "PAUSED" || currentStatus === "PAUSING"}
						<button
							class="btn bg-primary-500 hover:bg-primary-400 text-white px-3 py-1 text-xs font-bold rounded transition-colors disabled:opacity-50"
							onclick={handleResume}
							disabled={isActionPending}
						>
							Resume
						</button>
					{:else}
						<button
							class="btn bg-tertiary-500 hover:bg-tertiary-400 text-white px-3 py-1 text-xs font-bold rounded transition-colors disabled:opacity-50"
							onclick={() => handlePause(false)}
							disabled={isActionPending}
						>
							Pause
						</button>
					{/if}

					<button
						class="btn bg-error-500 hover:bg-error-400 text-white px-3 py-1 text-xs font-bold rounded transition-colors disabled:opacity-50"
						onclick={() => handlePause(true)}
						disabled={isActionPending}
					>
						Stop
					</button>
				</div>
			{/if}

			{#if wsStore}
				<div class="flex items-center gap-2 px-3 py-1.5 rounded-full bg-surface-800 border {wsStore.isConnected ? 'border-success-500/50' : 'border-error-500/50'}" title="{wsStore.eventsReceived} events received">
					<div class="w-2 h-2 rounded-full {wsStore.isConnected ? 'bg-success-500 animate-pulse' : 'bg-error-500'}"></div>
					<span class="text-xs font-bold {wsStore.isConnected ? 'text-success-500' : 'text-error-500'}">
						{wsStore.isConnected ? 'LIVE' : 'DISCONNECTED'}
					</span>
					<span class="text-[10px] text-surface-400 font-mono ml-1 px-1.5 py-0.5 bg-surface-900 rounded">{wsStore.eventsReceived}</span>
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
		<!-- Left Sidebar: Ensembles Dashboard -->
		<section class="bg-surface-800 border border-surface-700 rounded-lg p-4 shadow-lg flex flex-col h-full overflow-hidden">
			<EnsemblesSidebar
				experimentId={data.experimentId}
				executionId={data.executionId}
				events={wsStore?.statusEvents || []}
				totalIterations={totalIterations}
				numSteps={numSteps}
				selectedIteration={selectedIteration}
				selectedRealization={selectedRealization}
				selectedUpdate={selectedUpdate}
				onSelectIteration={handleSelectIteration}
				onSelectRealization={handleSelectRealization}
				onSelectUpdate={handleSelectUpdate}
				onSelectOverview={handleSelectOverview}
				/>
				</section>

				<!-- Right Content: Multi-tab workspace -->
				<section class="bg-surface-800 border border-surface-700 rounded-lg shadow-lg flex flex-col h-full overflow-hidden min-w-0">
				<header class="flex-none flex border-b border-surface-700 bg-surface-900 overflow-x-auto">
				<button
					class="px-4 py-2 text-sm font-bold border-b-2 whitespace-nowrap transition-colors {activeTab === 'updates' ? 'border-primary-500 text-primary-500' : 'border-transparent text-surface-400 hover:text-surface-200 hover:bg-surface-800'}"
					onclick={() => activeTab = 'updates'}
				>
					Updates
				</button>
				<button
					class="px-4 py-2 text-sm font-bold border-b-2 whitespace-nowrap transition-colors {activeTab === 'realizations' ? 'border-primary-500 text-primary-500' : 'border-transparent text-surface-400 hover:text-surface-200 hover:bg-surface-800'}"
					onclick={() => activeTab = 'realizations'}
				>
					Realizations
				</button>
				<button
					class="px-4 py-2 text-sm font-bold border-b-2 whitespace-nowrap transition-colors {activeTab === 'parameters' ? 'border-primary-500 text-primary-500' : 'border-transparent text-surface-400 hover:text-surface-200 hover:bg-surface-800'}"
					onclick={() => activeTab = 'parameters'}
				>
					Parameters
				</button>
				<button
					class="px-4 py-2 text-sm font-bold border-b-2 whitespace-nowrap transition-colors {activeTab === 'responses' ? 'border-primary-500 text-primary-500' : 'border-transparent text-surface-400 hover:text-surface-200 hover:bg-surface-800'}"
					onclick={() => activeTab = 'responses'}
				>					Responses
				</button>
				<button
					class="px-4 py-2 text-sm font-bold border-b-2 whitespace-nowrap transition-colors {activeTab === 'observations' ? 'border-primary-500 text-primary-500' : 'border-transparent text-surface-400 hover:text-surface-200 hover:bg-surface-800'}"
					onclick={() => activeTab = 'observations'}
				>
					Observations
				</button>
				<button
					class="px-4 py-2 text-sm font-bold border-b-2 whitespace-nowrap transition-colors {activeTab === 'console' ? 'border-primary-500 text-primary-500' : 'border-transparent text-surface-400 hover:text-surface-200 hover:bg-surface-800'}"
					onclick={() => activeTab = 'console'}
				>					Logs
				</button>
			</header>
			<div class="flex-auto overflow-hidden min-h-0 relative p-4">
				{#if activeTab === 'console'}
					<VirtualizedTerminal
						experimentId={data.experimentId}
						executionId={data.executionId}
						isRunning={!isFinished}
					/>
				{:else if activeTab === 'updates'}
					<div class="flex flex-col h-full overflow-y-auto gap-4">
						<ExperimentSummaryTab
							experimentId={data.experimentId}
							executionId={data.executionId}
							totalIterations={totalIterations}
							events={wsStore?.statusEvents || []}
						/>

						<div class="flex flex-row flex-wrap gap-4 items-start w-full">
							{#if selectedUpdate !== null}
								<div class="flex-none w-full md:w-[600px] max-w-full">
									<div class="bg-surface-900 border border-surface-700 rounded-lg shadow-lg overflow-hidden">
										<UpdateInfoTab
											experimentId={data.experimentId}
											executionId={data.executionId}
											iteration={selectedUpdate}
										/>
									</div>
								</div>
							{:else}
								{#each Array.from({length: totalIterations - 1}, (_, i) => i) as iter}
									<div class="flex-none w-full md:w-[450px] max-w-full">
										<div class="bg-surface-900 border border-surface-700 rounded-lg shadow-lg overflow-hidden h-full">
											<UpdateInfoTab
												experimentId={data.experimentId}
												executionId={data.executionId}
												iteration={iter}
											/>
										</div>
									</div>
								{/each}
							{/if}
						</div>
					</div>
				{:else if activeTab === 'realizations'}
					<RealizationStatusTab
						events={wsStore?.statusEvents || []}
						selectedIteration={selectedIteration}
						selectedRealization={selectedRealization}
						numSteps={numSteps}
						onSelectRealization={handleSelectRealization}
					/>
				{:else if activeTab === 'responses'}
					<AnalysisDashboard
						experimentId={data.experimentId}
						executionId={data.executionId}
						totalIterations={totalIterations}
						dataType="responses"
						observations={data.config?.observations || []}
					/>
				{:else if activeTab === 'parameters'}
					<AnalysisDashboard
						experimentId={data.experimentId}
						executionId={data.executionId}
						totalIterations={totalIterations}
						dataType="parameters"
						observations={data.config?.observations || []}
					/>				{:else if activeTab === 'observations'}
					<div class="h-full flex flex-col gap-4 overflow-hidden">
						<header class="flex-none">
							<h3 class="text-sm font-bold text-surface-300">Observation Data</h3>
							<p class="text-xs text-surface-500 italic">Global observations configured for this experiment.</p>
						</header>
						<div class="flex-auto overflow-y-auto bg-surface-900 border border-surface-700 rounded-lg p-4 font-mono text-xs">
							{#if data.config?.observations && data.config.observations.length > 0}
								<table class="w-full text-left">
									<thead class="border-b border-surface-700 text-surface-400">
										<tr>
											<th class="py-2 px-1">Response</th>
											<th class="py-2 px-1">Key</th>
											<th class="py-2 px-1 text-right">Value</th>
											<th class="py-2 px-1 text-right">Std Dev</th>
										</tr>
									</thead>
									<tbody class="divide-y divide-surface-800">
										{#each data.config.observations as obs}
											<tr class="hover:bg-surface-800/50">
												<td class="py-2 px-1 text-primary-400">{obs.key.response}</td>
												<td class="py-2 px-1 text-surface-500">
													{Object.entries(obs.key).filter(([k]) => k !== 'response').map(([k,v]) => `${k}:${v}`).join(', ')}
												</td>
												<td class="py-2 px-1 text-right text-surface-200">{obs.value.toExponential(3)}</td>
												<td class="py-2 px-1 text-right text-surface-400">{obs.std_dev.toExponential(3)}</td>
											</tr>
										{/each}
									</tbody>
								</table>
							{:else}
								<div class="h-full flex items-center justify-center text-surface-500 italic">
									No observations configured.
								</div>
							{/if}
						</div>
					</div>
				{/if}
			</div>
		</section>
	</div>
</div>
