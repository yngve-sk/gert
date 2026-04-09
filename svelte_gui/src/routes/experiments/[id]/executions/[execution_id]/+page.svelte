<script lang="ts">
import { onDestroy, onMount } from "svelte";
import { page } from "$app/state";
import { ExecutionWebSocketStore } from "$lib/stores/websocket.svelte";

let wsStore: ExecutionWebSocketStore | null = $state(null);

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
</script>
<div class="flex flex-col gap-4 max-w-5xl">
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

		<!-- M7 WebSocket Pulse Indicator -->
		{#if wsStore}
			<div class="flex items-center gap-2 px-3 py-1.5 rounded-full bg-surface-800 border {wsStore.isConnected ? 'border-success-500/50' : 'border-error-500/50'}">
				<div class="w-2 h-2 rounded-full {wsStore.isConnected ? 'bg-success-500 animate-pulse' : 'bg-error-500'}"></div>
				<span class="text-xs font-bold {wsStore.isConnected ? 'text-success-500' : 'text-error-500'}">
					{wsStore.isConnected ? 'LIVE' : 'DISCONNECTED'}
				</span>
			</div>
		{/if}
	</header>

	{#if wsStore?.error}
		<aside class="bg-error-500/10 border border-error-500/50 rounded-lg p-3">
			<p class="text-xs text-error-400">{wsStore.error}</p>
		</aside>
	{/if}

	<section class="bg-surface-800 border border-surface-700 rounded-lg p-6 shadow-lg">
		<h2 class="text-sm font-bold text-surface-100 mb-4 border-b border-surface-700 pb-2">Real-Time Status Pulse</h2>

		<div class="grid grid-cols-2 md:grid-cols-4 gap-4">
			<!-- Statistics derived from the reactive store -->
			<div class="bg-surface-900 border border-surface-700 p-4 rounded text-center">
				<div class="text-[10px] uppercase tracking-widest text-surface-400 mb-1">Total Signals</div>
				<div class="text-xl font-mono font-bold text-primary-400">{wsStore?.statusEvents.length || 0}</div>
			</div>

			<div class="bg-surface-900 border border-surface-700 p-4 rounded text-center">
				<div class="text-[10px] uppercase tracking-widest text-surface-400 mb-1">Completed</div>
				<div class="text-xl font-mono font-bold text-success-500">
					{wsStore?.statusEvents.filter(e => e.status === 'COMPLETED').length || 0}
				</div>
			</div>

			<div class="bg-surface-900 border border-surface-700 p-4 rounded text-center">
				<div class="text-[10px] uppercase tracking-widest text-surface-400 mb-1">Running</div>
				<div class="text-xl font-mono font-bold text-warning-500">
					{wsStore?.statusEvents.filter(e => e.status === 'RUNNING').length || 0}
				</div>
			</div>

			<div class="bg-surface-900 border border-surface-700 p-4 rounded text-center">
				<div class="text-[10px] uppercase tracking-widest text-surface-400 mb-1">Failed</div>
				<div class="text-xl font-mono font-bold text-error-500">
					{wsStore?.statusEvents.filter(e => e.status === 'FAILED').length || 0}
				</div>
			</div>
		</div>

		{#if wsStore?.statusEvents.length === 0}
			<p class="text-surface-500 text-xs text-center mt-6 italic">Waiting for events...</p>
		{/if}
	</section>
</div>
