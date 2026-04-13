<script lang="ts">
import type { RealizationStatus } from "$lib/stores/websocket.svelte";
import { slide } from "svelte/transition";

interface Props {
	experimentId: string;
	executionId: string;
	events: RealizationStatus[];
	totalIterations: number;
	numSteps: number;
	selectedIteration: number | null;
	selectedRealization: number | null;
	selectedUpdate: number | null;
	onSelectIteration: (iter: number | null) => void;
	onSelectRealization: (iter: number, real: number | null) => void;
	onSelectUpdate: (iter: number | null) => void;
	onSelectOverview: () => void;
}

let {
	experimentId,
	executionId,
	events,
	totalIterations,
	numSteps,
	selectedIteration,
	selectedRealization,
	selectedUpdate,
	onSelectIteration,
	onSelectRealization,
	onSelectUpdate,
	onSelectOverview
}: Props = $props();

// Map iterations to their realization events
let iterationsMap = $derived.by(() => {
	const map = new Map<number, RealizationStatus[]>();
	for (const event of events) {
		if (!map.has(event.iteration)) {
			map.set(event.iteration, []);
		}
		map.get(event.iteration)?.push(event);
	}
	// Sort realizations within iterations
	for (const [_, reals] of map) {
		reals.sort((a, b) => a.realization_id - b.realization_id);
	}
	return map;
});

let allIterations = $derived(Array.from({ length: totalIterations }, (_, i) => i));
let isOverview = $derived(selectedIteration === null && selectedUpdate === null && selectedRealization === null);

function toggleIteration(iterNum: number) {
	if (selectedIteration === iterNum) {
		onSelectIteration(null);
		onSelectRealization(iterNum, null);
	} else {
		onSelectIteration(iterNum);
		onSelectRealization(iterNum, null);
	}
}

function toggleRealization(iterNum: number, realNum: number) {
	if (selectedIteration === iterNum && selectedRealization === realNum) {
		onSelectRealization(iterNum, null);
	} else {
		if (selectedIteration !== iterNum) {
			onSelectIteration(iterNum);
		}
		onSelectRealization(iterNum, realNum);
	}
}

function getRealizationColor(status: string) {
	switch(status) {
		case 'COMPLETED': return 'text-success-500';
		case 'FAILED': return 'text-error-500';
		case 'RUNNING': return 'text-warning-500 animate-pulse';
		default: return 'text-surface-400';
	}
}

function getStepColor(status: string) {
	switch(status) {
		case 'COMPLETED': return 'text-success-500';
		case 'FAILED': return 'text-error-500';
		case 'RUNNING': return 'text-warning-500 animate-pulse';
		default: return 'text-surface-500';
	}
}
</script>

<div class="flex flex-col h-full w-full">
	<h2 class="text-sm font-bold text-surface-100 border-b border-surface-700 pb-2 mb-3">Ensembles Dashboard</h2>

	<div class="flex-auto overflow-y-auto pr-2 flex flex-col gap-1">
		<button
			class="w-full flex items-center justify-between px-3 py-2 rounded text-sm font-bold transition-colors border mb-2 sticky top-0 z-20 shadow-md {isOverview ? 'bg-primary-500 border-primary-400 text-black shadow-[0_0_10px_rgba(var(--color-primary-500),0.3)]' : 'bg-surface-900 border-surface-700 text-surface-300 hover:bg-surface-800'}"
			onclick={onSelectOverview}
		>
			<span class="flex items-center gap-2">
				<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 {isOverview ? 'text-black' : 'text-surface-500'}" fill="none" viewBox="0 0 24 24" stroke="currentColor">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
				</svg>
				Experiment Overview
			</span>
		</button>

		{#if allIterations.length === 0}
			<div class="flex h-full items-center justify-center p-4">
				<p class="text-surface-500 text-xs italic text-center">Awaiting initialization...</p>
			</div>
		{:else}
			{#each allIterations as iterNum (iterNum)}
				{@const isIterExpanded = selectedIteration === iterNum}
				{@const iterEvents = iterationsMap.get(iterNum) || []}

				<!-- Ensemble Header -->
				<button
					class="w-full flex items-center justify-between px-3 py-2 rounded text-sm font-bold transition-colors border {isIterExpanded ? 'bg-surface-700 border-surface-600 text-primary-400' : 'bg-surface-900 border-surface-700 text-surface-300 hover:bg-surface-800'}"
					onclick={() => toggleIteration(iterNum)}
				>
					<span class="flex items-center gap-2">
						<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 transition-transform {isIterExpanded ? 'rotate-90 text-primary-400' : 'text-surface-500'}" viewBox="0 0 20 20" fill="currentColor">
							<path fill-rule="evenodd" d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 7.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z" clip-rule="evenodd" />
						</svg>
						Ensemble {iterNum}
					</span>
					<span class="text-[10px] font-mono text-surface-400 font-normal">
						{iterEvents.filter(e => e.status === 'COMPLETED').length}/{iterEvents.length} Reals
					</span>
				</button>

				<!-- Realizations List (Expanded) -->
				{#if isIterExpanded}
					<div class="flex flex-col pl-4 border-l border-surface-700 ml-4 py-1 gap-1" transition:slide={{duration: 200}}>
						{#if iterEvents.length === 0}
							<div class="text-[10px] text-surface-500 italic py-1 px-2">No realizations yet</div>
						{:else}
							{#each iterEvents as realEvent (realEvent.realization_id)}
								{@const isRealExpanded = selectedRealization === realEvent.realization_id}

								<button
									class="w-full flex items-center justify-between px-2 py-1.5 rounded text-xs transition-colors border {isRealExpanded ? 'bg-surface-800 border-surface-600 text-surface-100' : 'border-transparent text-surface-400 hover:bg-surface-800/50'}"
									onclick={() => toggleRealization(iterNum, realEvent.realization_id)}
								>
									<span class="flex items-center gap-2">
										<svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3 transition-transform {isRealExpanded ? 'rotate-90' : 'text-surface-600'}" viewBox="0 0 20 20" fill="currentColor">
											<path fill-rule="evenodd" d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 7.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z" clip-rule="evenodd" />
										</svg>
										Realization {realEvent.realization_id}
									</span>
									<span class="text-[10px] font-mono {getRealizationColor(realEvent.status)} font-bold">
										{realEvent.status}
									</span>
								</button>

								<!-- Steps List (Expanded) -->
								{#if isRealExpanded}
									<div class="flex flex-col pl-3 border-l border-surface-700 ml-3 py-1 gap-0.5" transition:slide={{duration: 150}}>
										{#if !realEvent.steps || realEvent.steps.length === 0}
											<div class="text-[10px] text-surface-500 italic px-2 py-1">No steps executed</div>
										{:else}
											<!-- Reverse the array to show newest (currently executing) at top, oldest at bottom -->
											{#each [...realEvent.steps].reverse() as step, i}
												<div class="flex items-center justify-between px-2 py-1 text-[10px] bg-surface-900/30 rounded border border-surface-800">
													<div class="flex items-center gap-2 truncate">
														<span class="w-1.5 h-1.5 rounded-full {getStepColor(step.status)}"></span>
														<span class="text-surface-300 truncate" title={step.name}>{step.name}</span>
													</div>
													<div class="flex items-center gap-2 flex-none pl-2">
														<span class="font-mono text-surface-500">{step.status}</span>
														<a
															href="/experiments/{experimentId}/executions/{executionId}/ensembles/{iterNum}/realizations/{realEvent.realization_id}/steps/{step.name}"
															class="text-primary-400 hover:text-primary-300 underline font-bold"
															onclick={(e) => e.stopPropagation()}
														>
															Details
														</a>
													</div>
												</div>
											{/each}
										{/if}
									</div>
								{/if}
							{/each}
						{/if}
					</div>
				{/if}

				<!-- Interleaved Update -->
				{#if iterNum < totalIterations - 1}
					<div class="flex items-center justify-center py-2 relative">
						<div class="absolute inset-0 flex items-center justify-center pointer-events-none">
							<div class="w-px h-full bg-surface-700"></div>
						</div>
						<button
							class="text-[10px] font-bold px-2 py-0.5 rounded-full z-10 transition-colors border {selectedUpdate === iterNum ? 'bg-tertiary-500 border-tertiary-400 text-black shadow-[0_0_10px_rgba(var(--color-tertiary-500),0.3)]' : 'bg-tertiary-500/20 border-tertiary-500/30 text-tertiary-400 hover:bg-tertiary-500/30'}"
							onclick={() => onSelectUpdate(selectedUpdate === iterNum ? null : iterNum)}
						>
							Update {iterNum}
						</button>
					</div>
				{/if}
			{/each}
		{/if}
	</div>
</div>
