<script lang="ts">
// biome-ignore lint/correctness/noUnusedImports: used in render
import { page } from "$app/state";
</script>

<div class="flex flex-col gap-4 max-w-4xl">
	<header class="flex items-center gap-4">
		<a href="/experiments" class="btn bg-surface-800 hover:bg-surface-700 text-surface-300 px-3 py-1.5 rounded border border-surface-700 text-sm transition-colors">
			&larr; Back
		</a>
		<div>
			<h1 class="text-2xl font-bold tracking-tight text-surface-50">Experiment Details</h1>
			<p class="text-sm font-mono text-surface-400 mt-1">{page.params.id}</p>
		</div>
	</header>

	<section class="bg-surface-800 border border-surface-700 rounded-lg p-8 text-center mt-4 shadow-lg">
		<p class="text-surface-400 text-sm italic">
			Execution Explorer (M6) will be implemented here.
		</p>
	</section>
</div>
