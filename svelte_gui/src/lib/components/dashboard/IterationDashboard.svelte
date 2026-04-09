<script lang="ts">
import type { RealizationStatus } from "$lib/stores/websocket.svelte";
// biome-ignore lint/correctness/noUnusedImports: used in HTML template
import IterationProgressBar from "./IterationProgressBar.svelte";

interface Props {
	events: RealizationStatus[];
	totalIterations: number;
}

let { events, totalIterations }: Props = $props();

// Group events by iteration
let iterationsMap = $derived.by(() => {
	const map = new Map<number, RealizationStatus[]>();
	for (const event of events) {
		if (!map.has(event.iteration)) {
			map.set(event.iteration, []);
		}
		map.get(event.iteration)?.push(event);
	}
	return map;
});

// A complete list of all iterations
let allIterations = $derived(
	Array.from({ length: totalIterations }, (_, i) => i)
);
</script>

<div class="flex flex-col gap-4 h-full">
	<h2 class="text-sm font-bold text-surface-100 border-b border-surface-700 pb-2">Iteration Dashboard</h2>

	<div class="flex-auto overflow-y-auto pr-2 flex flex-col gap-3">
		{#if allIterations.length === 0}
			<div class="flex h-full items-center justify-center p-8">
				<p class="text-surface-500 text-xs italic">Awaiting iteration initialization...</p>
			</div>
		{:else}
			{#each allIterations as iterNum (iterNum)}
				<IterationProgressBar iteration={iterNum} events={iterationsMap.get(iterNum) || []} />
			{/each}
		{/if}
	</div>
</div>
