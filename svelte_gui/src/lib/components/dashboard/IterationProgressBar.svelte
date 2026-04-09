<script lang="ts">
import type { RealizationStatus } from "$lib/stores/websocket.svelte";

interface Props {
	iteration: number;
	events: RealizationStatus[];
}

// biome-ignore lint/correctness/noUnusedVariables: used in Svelte 5 template bindings
let { iteration, events }: Props = $props();

// Derived statistics for this specific iteration
let total = $derived(events.length);
let completed = $derived(events.filter((e) => e.status === "COMPLETED").length);
let failed = $derived(events.filter((e) => e.status === "FAILED").length);
let running = $derived(events.filter((e) => e.status === "RUNNING").length);

// biome-ignore lint/correctness/noUnusedVariables: used in template bindings
let percentCompleted = $derived(total > 0 ? (completed / total) * 100 : 0);
// biome-ignore lint/correctness/noUnusedVariables: used in template bindings
let percentFailed = $derived(total > 0 ? (failed / total) * 100 : 0);
// biome-ignore lint/correctness/noUnusedVariables: used in template bindings
let percentRunning = $derived(total > 0 ? (running / total) * 100 : 0);

// biome-ignore lint/correctness/noUnusedVariables: used in template bindings
let isFinished = $derived(total > 0 && completed + failed === total);
</script>
<!-- L3 Inset: Iteration Progress Card -->
<div class="bg-surface-900 border border-surface-700 rounded p-4 flex flex-col gap-3 transition-colors hover:border-surface-600">
	<header class="flex justify-between items-end">
		<div>
			<h4 class="text-sm font-bold text-surface-100 flex items-center gap-2">
				Iteration {iteration}
				{#if isFinished}
					<span class="badge bg-surface-700 text-surface-300 text-[10px] font-bold px-1.5 py-0.5 rounded border border-surface-600">FINISHED</span>
				{:else if running > 0}
					<span class="badge bg-warning-500/20 text-warning-500 border border-warning-500/50 text-[10px] font-bold px-1.5 py-0.5 rounded animate-pulse">ACTIVE</span>
				{/if}
			</h4>
		</div>
		<div class="text-xs font-mono text-surface-400">
			<span class="text-success-500" title="Completed">{completed}</span> /
			<span class="text-error-500" title="Failed">{failed}</span> /
			<span>{total}</span>
		</div>
	</header>

	<!-- Progress Bar Stack -->
	<div class="h-2 w-full bg-surface-950 rounded-full overflow-hidden flex shadow-inner">
		{#if total > 0}
			<div class="h-full bg-success-500 transition-all duration-300 ease-out" style="width: {percentCompleted}%" title="Completed"></div>
			<div class="h-full bg-error-500 transition-all duration-300 ease-out" style="width: {percentFailed}%" title="Failed"></div>
			<div class="h-full bg-warning-500 transition-all duration-300 ease-out animate-pulse" style="width: {percentRunning}%" title="Running"></div>
		{/if}
	</div>
</div>
