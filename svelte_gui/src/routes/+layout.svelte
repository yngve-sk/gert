<script lang="ts">
	import "./layout.css";
	// biome-ignore lint/correctness/noUnusedImports: used in svelte:head
	import favicon from "$lib/assets/favicon.svg";

	// biome-ignore lint/correctness/noUnusedVariables: used in render
	let { children } = $props();
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
	<title>GERT Workbench</title>
</svelte:head>

<div class="h-screen w-full flex flex-col overflow-hidden bg-surface-50-950-token text-surface-900-50-token">
	<!-- Header -->
	<header class="flex-none w-full border-b border-surface-200-800-token bg-surface-100-900-token p-4 flex items-center justify-between z-10">
		<strong class="text-xl font-bold uppercase tracking-wider">GERT</strong>
	</header>

	<div class="flex-auto w-full flex overflow-hidden">
		<!-- Sidebar -->
		<aside class="flex-none w-64 bg-surface-100-900-token border-r border-surface-200-800-token overflow-y-auto">
			<nav class="p-4 space-y-4">
				<div>
					<h3 class="text-xs font-bold uppercase opacity-50 mb-2 tracking-widest">Workspace</h3>
					<ul class="space-y-1">
						<li><a href="/" class="block px-3 py-2 hover:bg-surface-200-800-token rounded-token transition-colors">Dashboard</a></li>
						<li><a href="/experiments" class="block px-3 py-2 hover:bg-surface-200-800-token rounded-token transition-colors">Experiments</a></li>
					</ul>
				</div>
			</nav>
		</aside>

		<!-- Main Content -->
		<main class="flex-auto w-full h-full p-4 md:p-8 overflow-y-auto relative">
			{@render children()}
		</main>
	</div>
</div>
