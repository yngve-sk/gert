<script lang="ts">
	// biome-ignore lint/correctness/noUnusedImports: used in render
	import { page } from "$app/state";
</script>
<div class="flex flex-col gap-4 max-w-5xl">
	<header class="flex items-center gap-4">
		<a href="/experiments/{page.params.id}" class="btn bg-surface-800 hover:bg-surface-700 text-surface-300 px-3 py-1.5 rounded border border-surface-700 text-sm transition-colors">
			&larr; Back
		</a>
		<div>
			<h1 class="text-2xl font-bold tracking-tight text-surface-50">Execution Inspector</h1>
			<p class="text-sm font-mono text-surface-400 mt-1">{page.params.execution_id}</p>
		</div>
	</header>

	<section class="bg-surface-800 border border-surface-700 rounded-lg p-8 text-center mt-4 shadow-lg">
		<h2 class="text-lg font-bold text-surface-100 mb-2">M7 & M8 Will Go Here</h2>
		<p class="text-surface-400 text-sm">
			This dashboard will contain the WebSocket Pulse, Execution Controls (Start/Pause), and the live Virtualized Terminal logs.
		</p>
	</section>
</div>
