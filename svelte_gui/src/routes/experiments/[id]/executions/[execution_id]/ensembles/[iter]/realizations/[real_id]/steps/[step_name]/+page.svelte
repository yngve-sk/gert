<script lang="ts">
import type { PageData } from "./$types";

let { data }: { data: PageData } = $props();

let activeTab = $state<"stdout" | "stderr">("stdout");
</script>

<div class="flex flex-col gap-4 w-full h-full">
	<header class="flex items-start justify-between border-b border-surface-800 bg-surface-900 px-4 py-6 rounded-t-lg shadow-sm">
		<div>
			<h1 class="text-2xl font-bold tracking-tight text-surface-50 flex items-center gap-2">
				<svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 text-primary-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
				</svg>
				Step Detail: {data.stepName}
			</h1>
			<p class="text-xs font-mono text-surface-400 mt-2">
				Ensemble <span class="text-surface-200">{data.iteration}</span>
				| Realization <span class="text-surface-200">{data.realizationId}</span>
			</p>
			<p class="text-[10px] font-mono text-surface-500 mt-1 truncate">{data.executionId}</p>
		</div>
		<div class="flex items-center gap-3">
			<a href="/experiments/{data.experimentId}/executions/{data.executionId}" class="btn bg-surface-800 hover:bg-surface-700 text-surface-300 px-4 py-2 rounded transition-colors border border-surface-700 font-medium">
				&larr; Back to Execution
			</a>
		</div>
	</header>

	{#if data.error}
		<aside class="bg-error-500/10 border border-error-500/50 rounded-lg p-4">
			<h3 class="text-error-500 font-bold text-sm">Error Loading Logs</h3>
			<p class="text-xs text-error-400 mt-1">{data.error}</p>
		</aside>
	{:else if data.logs}
		<section class="bg-surface-800 border border-surface-700 rounded-lg shadow-lg flex flex-col h-full overflow-hidden min-h-0">
			<header class="flex border-b border-surface-700 bg-surface-900 flex-none">
				<button
					class="px-4 py-2 text-sm font-bold border-b-2 whitespace-nowrap transition-colors {activeTab === 'stdout' ? 'border-primary-500 text-primary-500' : 'border-transparent text-surface-400 hover:text-surface-200 hover:bg-surface-800'}"
					onclick={() => activeTab = 'stdout'}
				>
					STDOUT
				</button>
				<button
					class="px-4 py-2 text-sm font-bold border-b-2 whitespace-nowrap transition-colors {activeTab === 'stderr' ? 'border-error-500 text-error-500' : 'border-transparent text-surface-400 hover:text-surface-200 hover:bg-surface-800'}"
					onclick={() => activeTab = 'stderr'}
				>
					STDERR
				</button>
			</header>

			<div class="flex-auto overflow-y-auto p-4 bg-surface-950 font-mono text-xs text-surface-300 leading-relaxed whitespace-pre-wrap break-words">
				{#if activeTab === 'stdout'}
					{#if !data.logs.stdout || data.logs.stdout.trim() === ''}
						<span class="text-surface-500 italic">No standard output.</span>
					{:else}
						{data.logs.stdout}
					{/if}
				{:else}
					{#if !data.logs.stderr || data.logs.stderr.trim() === ''}
						<span class="text-surface-500 italic">No standard errors.</span>
					{:else}
						<span class="text-error-300">{data.logs.stderr}</span>
					{/if}
				{/if}
			</div>
		</section>
	{/if}
</div>
