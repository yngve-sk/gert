<script lang="ts">
import type { PageData } from "./$types";

// biome-ignore lint/correctness/noUnusedVariables: used in render
let { data }: { data: PageData } = $props();
</script>
<div class="flex flex-col gap-4">
	<header>
		<h1 class="text-2xl font-bold tracking-tight text-surface-50">Experiment Browser</h1>
		<p class="text-sm text-surface-400 mt-1">Select an experiment to view its executions and parameters.</p>
	</header>

	{#if data.error}
		<aside class="bg-error-500/10 border border-error-500/50 rounded-lg p-4">
			<h3 class="text-error-500 font-bold text-sm">Connection Error</h3>
			<p class="text-xs text-error-400 mt-1">
				Could not connect to the GERT backend. Please ensure the Python server is running (`gert server --port 8000`).
			</p>
			<p class="text-xs text-error-500/80 mt-2 font-mono">Details: {data.error}</p>
		</aside>
	{/if}

	<!-- L2: Container -->
	<section class="bg-surface-800 border border-surface-700 rounded-lg overflow-hidden shadow-lg">
		<header class="p-3 border-b border-surface-700 bg-surface-800 flex justify-between items-center">
			<h2 class="text-sm font-bold text-surface-100">Registered Experiments</h2>
			<span class="badge bg-surface-700 text-surface-300 text-xs font-bold px-2 py-0.5 rounded border border-surface-600">
				{data.experiments.length} Total
			</span>
		</header>

		<div class="p-0">
			{#if data.experiments.length === 0 && !data.error}
				<div class="p-8 text-center text-surface-400 text-sm italic">
					No experiments found. Submit an experiment via the CLI first.
				</div>
			{:else}
				<ul class="divide-y divide-surface-700/50">
					{#each data.experiments as experiment}
						<li>
							<!-- L3: Hoverable Inset Row -->
							<a
								href="/experiments/{experiment.id}"
								class="block p-4 hover:bg-surface-700 transition-colors group cursor-pointer"
							>
								<div class="flex items-center justify-between">
									<div class="flex flex-col gap-1">
										<strong class="text-primary-400 text-base font-bold group-hover:text-primary-300 transition-colors">
											{experiment.name}
										</strong>
										<span class="text-xs font-mono text-surface-500">{experiment.id}</span>
									</div>
									<div class="text-surface-500 group-hover:text-surface-300 transition-colors">
										<!-- Simple right arrow SVG icon -->
										<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
											<path fill-rule="evenodd" d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z" clip-rule="evenodd" />
										</svg>
									</div>
								</div>
							</a>
						</li>
					{/each}
				</ul>
			{/if}
		</div>
	</section>
</div>
