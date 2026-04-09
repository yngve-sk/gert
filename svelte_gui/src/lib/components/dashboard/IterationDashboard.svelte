<script lang="ts">
import type { RealizationStatus } from "$lib/stores/websocket.svelte";
// biome-ignore lint/correctness/noUnusedImports: used in HTML template
import IterationProgressBar from "./IterationProgressBar.svelte";

interface Props {
	events: RealizationStatus[];
}

let { events }: Props = $props();

// Group events by iteration
let iterationsMap = $derived(() => {
	const map = new Map<number, RealizationStatus[]>();
	for (const event of events) {
		if (!map.has(event.iteration)) {
			map.set(event.iteration, []);
		}
		map.get(event.iteration)?.push(event);
	}
	return map;
});

// Sorted list of iterations (0, 1, 2, ...)
// biome-ignore lint/correctness/noUnusedVariables: used in Svelte 5 template bindings
let sortedIterations = $derived(
	Array.from(iterationsMap().keys()).sort((a, b) => a - b),
);
</script>

<div class="flex flex-col gap-4 h-full">
	<h2 class="text-sm font-bold text-surface-100 border-b border-surface-700 pb-2">Iteration Dashboard</h2>

	<div class="flex-auto overflow-y-auto pr-2 flex flex-col gap-3">
		{#if sortedIterations.length === 0}
			<div class="flex h-full items-center justify-center p-8">
				<p class="text-surface-500 text-xs italic">Awaiting iteration initialization...</p>
			</div>
		{:else}
			{#each sortedIterations as iterNum (iterNum)}
				<IterationProgressBar iteration={iterNum} events={iterationsMap().get(iterNum) || []} />
			{/each}
		{/if}
	</div>
</div>
