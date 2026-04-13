<script lang="ts">
import type { RealizationStatus } from "$lib/stores/websocket.svelte";

interface Props {
	events: RealizationStatus[];
	selectedIteration: number | null;
	selectedRealization: number | null;
	numSteps: number;
	onSelectRealization: (iter: number, real: number) => void;
}

let { events, selectedIteration, selectedRealization, numSteps, onSelectRealization }: Props = $props();

let filteredEvents = $derived.by(() => {
	// Filter out overarching execution updates (realization_id == -1)
	let evs = events.filter(e => e.realization_id !== -1);

	if (selectedIteration !== null) {
		evs = evs.filter(e => e.iteration === selectedIteration);
	}

	// Sort by iteration, then realization
	evs.sort((a, b) => {
		if (a.iteration === b.iteration) {
			return a.realization_id - b.realization_id;
		}
		return a.iteration - b.iteration;
	});

	return evs;
});

function getActiveStepName(e: RealizationStatus): string {
	if (!e.steps || e.steps.length === 0) return "Init";
	if (e.status === "COMPLETED") return "Done";

	const activeStep = e.steps.find(s => s.status !== "COMPLETED");
	if (activeStep) return activeStep.name;

	return e.steps[e.steps.length - 1].name;
}

function truncateName(name: string): string {
	if (name === "Init" || name === "Done") return name;
	return name.length > 4 ? name.substring(0, 4) + ".." : name;
}
</script>

<div class="h-full w-full bg-surface-900 border border-surface-700 rounded-lg overflow-y-auto p-4 flex flex-col gap-4">
	<header class="flex justify-between items-center pb-2 border-b border-surface-700 sticky top-0 bg-surface-900 z-10">
		<h3 class="text-sm font-bold text-surface-200">
			{#if selectedIteration !== null}
				Ensemble {selectedIteration} Realizations
			{:else}
				All Realizations
			{/if}
		</h3>
		<span class="text-xs text-surface-400 font-mono">Count: {filteredEvents.length}</span>
	</header>

	{#if filteredEvents.length === 0}
		<div class="flex-auto flex items-center justify-center text-surface-500 text-sm italic">
			No realizations found for the current selection.
		</div>
	{:else}
		<div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
			{#each filteredEvents as e (e.iteration + '-' + e.realization_id)}
				{@const isSelected = selectedIteration === e.iteration && selectedRealization === e.realization_id}
				{@const completedSteps = e.steps ? e.steps.filter(s => s.status === "COMPLETED").length : 0}
				{@const percent = Math.max(0, Math.min(100, (completedSteps / numSteps) * 100))}
				{@const activeName = getActiveStepName(e)}

				<button
					class="flex flex-col bg-surface-800 border rounded p-2 text-left transition-colors relative overflow-hidden group {isSelected ? 'border-primary-500 ring-1 ring-primary-500/50' : 'border-surface-600 hover:border-surface-500'}"
					onclick={() => onSelectRealization(e.iteration, e.realization_id)}
				>
					<!-- Status Background Gradient -->
					<div class="absolute inset-0 opacity-10 pointer-events-none transition-colors
						{e.status === 'COMPLETED' ? 'bg-success-500' : e.status === 'FAILED' ? 'bg-error-500' : e.status === 'RUNNING' ? 'bg-warning-500' : 'bg-surface-700'}">
					</div>

					<div class="flex justify-between items-start w-full mb-2 z-10">
						<div class="flex flex-col leading-none">
							<span class="text-[9px] font-bold text-surface-400 uppercase tracking-widest">Real {e.realization_id}</span>
							<span class="text-xs font-bold text-surface-200">Iter {e.iteration}</span>
						</div>
						<span class="text-[9px] font-mono font-bold {e.status === 'COMPLETED' ? 'text-success-400' : e.status === 'FAILED' ? 'text-error-400' : e.status === 'RUNNING' ? 'text-warning-400 animate-pulse' : 'text-surface-500'}">
							{e.status.substring(0, 4)}
						</span>
					</div>

					<div class="flex justify-between w-full text-[10px] font-mono text-surface-400 mb-1 z-10">
						<span title={activeName}>{truncateName(activeName)}</span>
						<span>{completedSteps}/{numSteps}</span>
					</div>

					<div class="w-full h-1.5 bg-surface-950 rounded-full overflow-hidden flex z-10 shadow-inner">
						<div
							class="h-full transition-all duration-300 ease-out {e.status === 'FAILED' ? 'bg-error-500' : e.status === 'COMPLETED' ? 'bg-success-500' : 'bg-warning-500'}"
							style="width: {percent}%"
						></div>
					</div>
				</button>
			{/each}
		</div>
	{/if}
</div>
