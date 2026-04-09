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

<!-- L0: Ground (bg-surface-950) -->
<div class="h-screen w-full flex flex-col overflow-hidden bg-surface-950 text-surface-50">

	<!-- Header (L1) -->
	<header class="flex-none w-full border-b border-surface-800 bg-surface-900 px-3 py-2 flex items-center justify-between z-10">
		<div class="flex items-center gap-4">
			<strong class="text-sm font-bold uppercase tracking-widest text-primary-500">GERT</strong>
			<span class="text-xs text-surface-400 font-mono">v0.1.0-dev</span>
		</div>
		<div class="flex items-center gap-2">
			<!-- Socket Status Indicator -->
			<div class="w-2 h-2 rounded-full bg-error-500 animate-pulse" title="Disconnected"></div>
		</div>
	</header>

	<div class="flex-auto w-full flex overflow-hidden">
		<!-- Pane 1: Nav Sidebar (L1) -->
		<aside class="flex-none w-56 bg-surface-900 border-r border-surface-800 overflow-y-auto">
			<nav class="p-2 space-y-4">
				<div>
					<h3 class="text-[10px] font-bold uppercase opacity-50 mb-1 px-2 tracking-widest">Workspace</h3>
					<ul class="space-y-0.5 text-sm">
						<li>
							<a href="/" class="block px-2 py-1.5 hover:bg-surface-800 rounded transition-colors border border-transparent hover:border-surface-700">
								Dashboard
							</a>
						</li>
						<li>
							<a href="/experiments" class="block px-2 py-1.5 hover:bg-surface-800 rounded transition-colors border border-transparent hover:border-surface-700">
								Experiments
							</a>
						</li>
					</ul>
				</div>
			</nav>
		</aside>

		<!-- Pane 2: Multi-tab Workspace (L1 background, holds L2/L3) -->
		<main class="flex-auto min-w-0 h-full flex flex-col bg-surface-950 relative">
			<!-- Tab Bar (L2) -->
			<div class="flex-none w-full bg-surface-900 border-b border-surface-800 flex px-2 pt-2 gap-1 overflow-x-auto">
				<div class="px-3 py-1.5 bg-surface-800 border-t border-x border-surface-700 rounded-t-md text-xs font-medium text-surface-100 cursor-pointer">
					Overview
				</div>
				<div class="px-3 py-1.5 bg-surface-900/50 hover:bg-surface-800 text-surface-400 border-t border-x border-transparent rounded-t-md text-xs font-medium cursor-pointer transition-colors">
					Execution Explorer
				</div>
			</div>

			<!-- Workspace Content Area -->
			<div class="flex-auto overflow-y-auto p-4 flex flex-col gap-4">
				{@render children()}
			</div>
		</main>

		<!-- Pane 3: Detail Drawer (L1) - Hidden by default on small screens -->
		<aside class="hidden xl:flex flex-col flex-none w-80 bg-surface-900 border-l border-surface-800 overflow-y-auto shadow-2xl z-20">
			<div class="p-3 border-b border-surface-800 flex justify-between items-center bg-surface-900 sticky top-0">
				<h3 class="text-xs font-bold uppercase tracking-widest text-surface-300">Detail Inspector</h3>
			</div>

			<div class="p-4 flex flex-col gap-4">
				<div class="text-xs text-surface-400 italic">Select an item to inspect.</div>
			</div>
		</aside>
	</div>
</div>
