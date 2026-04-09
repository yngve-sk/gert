<script lang="ts">
// biome-ignore lint/correctness/noUnusedImports: used in HTML template
import PlotContainer from "$lib/components/plotting/PlotContainer.svelte";
import type { PageData } from "./$types";

// biome-ignore lint/correctness/noUnusedVariables: used in render
let { data }: { data: PageData } = $props();

// biome-ignore lint/correctness/noUnusedVariables: used in render template
function getStatusColor(status: string): string {
	switch (status.toUpperCase()) {
		case "COMPLETED":
			return "bg-success-500 text-black";
		case "FAILED":
			return "bg-error-500 text-white";
		case "RUNNING":
			return "bg-warning-500 text-black";
		case "PAUSED":
			return "bg-tertiary-500 text-white";
		default:
			return "bg-surface-500 text-white";
	}
}
</script>

<div class="flex flex-col gap-4 max-w-6xl w-full">
	<header class="flex items-center gap-4">
		<a href="/experiments" class="btn bg-surface-800 hover:bg-surface-700 text-surface-300 px-3 py-1.5 rounded border border-surface-700 text-sm transition-colors">
			&larr; Back
		</a>
		<div>
			<h1 class="text-2xl font-bold tracking-tight text-surface-50">
				{data.config ? data.config.name : 'Experiment Details'}
			</h1>
			<p class="text-sm font-mono text-surface-400 mt-1">{data.experimentId}</p>
		</div>
	</header>

	{#if data.error}
		<aside class="bg-error-500/10 border border-error-500/50 rounded-lg p-4">
			<h3 class="text-error-500 font-bold text-sm">Error Loading Executions</h3>
			<p class="text-xs text-error-400 mt-1">{data.error}</p>
		</aside>
	{/if}

	<div class="grid grid-cols-1 xl:grid-cols-[1fr_400px] gap-4 w-full items-start">
		<!-- L2 Container: Executions List -->
		<section class="bg-surface-800 border border-surface-700 rounded-lg overflow-hidden shadow-lg w-full">
			<header class="p-3 border-b border-surface-700 bg-surface-800 flex justify-between items-center">
				<h2 class="text-sm font-bold text-surface-100">Execution History</h2>
				<span class="badge bg-surface-700 text-surface-300 text-xs font-bold px-2 py-0.5 rounded border border-surface-600">
					{data.executions.length} Total
				</span>
			</header>

			<div class="overflow-x-auto w-full">
				{#if data.executions.length === 0 && !data.error}
					<div class="p-8 text-center text-surface-400 text-sm italic">
						No executions found for this experiment.
					</div>
				{:else if data.executions.length > 0}
					<table class="w-full text-left text-sm whitespace-nowrap table-auto">
						<thead class="bg-surface-800 border-b border-surface-700 text-xs uppercase tracking-wider text-surface-400">
							<tr>
								<th class="px-4 py-3 font-semibold">Execution ID</th>
								<th class="px-4 py-3 font-semibold">Status</th>
								<th class="px-4 py-3 font-semibold text-right">Iter</th>
								<th class="px-4 py-3 font-semibold text-right text-success-500">Complete</th>
								<th class="px-4 py-3 font-semibold text-right text-error-500">Failed</th>
								<th class="px-4 py-3 font-semibold text-center">Action</th>
							</tr>
						</thead>
						<tbody class="divide-y divide-surface-700/50 bg-surface-900/20">
							{#each data.executions as exec}
								<tr class="hover:bg-surface-700/50 transition-colors group">
									<td class="px-4 py-3 min-w-[200px] max-w-[300px]">
										<div class="flex flex-col">
											<span class="font-mono text-primary-400 group-hover:text-primary-300 truncate block">{exec.execution_id.split('_').pop() || exec.execution_id}</span>
											<span class="text-[10px] text-surface-500 font-mono block truncate" title={exec.execution_id}>{exec.execution_id.substring(0, 8)}...</span>
										</div>
									</td>
									<td class="px-4 py-3">
										<span class="badge {getStatusColor(exec.status)} text-[10px] font-bold px-2 py-0.5 rounded">
											{exec.status}
										</span>
									</td>
									<td class="px-4 py-3 text-right font-mono text-surface-300">
										{exec.current_iteration}
									</td>
									<td class="px-4 py-3 text-right font-mono text-surface-300">
										{exec.completed_realizations.length}
									</td>
									<td class="px-4 py-3 text-right font-mono">
										<span class={exec.failed_realizations.length > 0 ? "text-error-400 font-bold" : "text-surface-500"}>
											{exec.failed_realizations.length}
										</span>
									</td>
									<td class="px-4 py-3 text-center">
										<!-- Drill down to execution details -->
										<a
											href="/experiments/{data.experimentId}/executions/{exec.execution_id}"
											class="btn bg-surface-700 hover:bg-surface-600 text-surface-100 text-xs px-3 py-1 rounded transition-colors whitespace-nowrap"
										>
											Inspect
										</a>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				{/if}
			</div>
		</section>

		<!-- Right Column: Convergence Plot -->
		<section class="bg-surface-800 border border-surface-700 rounded-lg shadow-lg flex flex-col h-full min-h-[300px]">
			<header class="p-3 border-b border-surface-700 bg-surface-800">
				<h2 class="text-sm font-bold text-surface-100">Convergence: {data.latestExecutionId ? data.latestExecutionId.substring(0,8) + '...' : 'Latest'}</h2>
			</header>
			<div class="flex-auto p-4 w-full overflow-hidden">
				<PlotContainer summaries={data.summaries} />
			</div>
		</section>
	</div>
</div>
