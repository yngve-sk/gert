<script lang="ts">
import "./layout.css";
// biome-ignore lint/correctness/noUnusedImports: used in svelte:head
import favicon from "$lib/assets/favicon.svg";
import type { LayoutData } from "./$types";

import { onMount, onDestroy } from "svelte";
import { getSystemInfo } from "$lib/api/client";

// biome-ignore lint/correctness/noUnusedVariables: used in render
let { data, children }: { data: LayoutData; children: any } = $props();

let systemInfo = $state(data.systemInfo);
let isConnected = $state(false);
let currentTime = $state(new Date());
let timerInterval: number;
let systemInterval: number;

$effect(() => {
	if (data.systemInfo !== null && !isConnected) {
		systemInfo = data.systemInfo;
		isConnected = true;
	}
});

onMount(() => {
	// Update uptime every second
	timerInterval = window.setInterval(() => {
		currentTime = new Date();
	}, 1000);

	// Poll system info every 3 seconds
	systemInterval = window.setInterval(async () => {
		try {
			let fetcher = window.fetch;
			if (window.location.pathname.includes("/_app/")) {
				fetcher = (input: RequestInfo | URL, init?: RequestInit) => {
					const targetUrl = new URL(input.toString(), window.location.origin);
					return window.fetch(targetUrl, init);
				};
			}
			const info = await getSystemInfo(fetcher);
			systemInfo = info;
			isConnected = true;
		} catch {
			isConnected = false;
		}
	}, 3000);
});

onDestroy(() => {
	if (timerInterval) clearInterval(timerInterval);
	if (systemInterval) clearInterval(systemInterval);
});

function formatUptime(startTimeStr: string | undefined, current: Date): string {
	if (!startTimeStr) return "Unknown";
	const start = new Date(startTimeStr);
	const diffMs = current.getTime() - start.getTime();
	const diffSec = Math.floor(diffMs / 1000);
	const diffMin = Math.floor(diffSec / 60);
	const diffHr = Math.floor(diffMin / 60);

	if (diffHr > 0) return `${diffHr}h ${diffMin % 60}m`;
	if (diffMin > 0) return `${diffMin}m ${diffSec % 60}s`;
	return `${diffSec}s`;
}
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
			<span class="text-xs text-surface-400 font-mono">{systemInfo?.version || 'v0.1.0-dev'}</span>
		</div>
		<div class="flex items-center gap-2">
			<!-- Socket Status Indicator -->
			<div class="flex items-center gap-2 px-2 py-0.5 rounded bg-surface-800 border border-surface-700">
				<div class="w-1.5 h-1.5 rounded-full {isConnected ? 'bg-success-500 animate-pulse' : 'bg-error-500'}"></div>
				<span class="text-[10px] font-bold text-surface-400 uppercase tracking-tighter">
					{isConnected ? 'Connected' : 'Offline'}
				</span>
			</div>
		</div>
	</header>

	<div class="flex-auto w-full flex overflow-hidden">
		<!-- Pane 1: Nav Sidebar (L1) -->
		<aside class="flex-none w-56 bg-surface-900 border-r border-surface-800 flex flex-col overflow-hidden">
			<nav class="flex-auto p-2 space-y-4 overflow-y-auto">
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

			<!-- Server Info Panel (Bottom Left) -->
			<div class="flex-none p-3 border-t border-surface-800 bg-surface-950/30">
				<h3 class="text-[9px] font-bold uppercase text-surface-500 mb-2 tracking-widest flex items-center justify-between">
					Server Status
					{#if isConnected}
						<span class="w-1.5 h-1.5 rounded-full bg-success-500 animate-ping"></span>
					{/if}
				</h3>
				{#if systemInfo}
					<div class="space-y-1.5">
						<div class="flex justify-between items-center text-[10px]">
							<span class="text-surface-400">Uptime</span>
							<span class="font-mono text-surface-200">{formatUptime(systemInfo.start_time, currentTime)}</span>
						</div>
						<div class="flex justify-between items-center text-[10px]">
							<span class="text-surface-400">Experiments</span>
							<span class="font-bold text-primary-400">{systemInfo.num_experiments}</span>
						</div>
						<div class="flex justify-between items-center text-[10px]">
							<span class="text-surface-400">Active Runs</span>
							<span class="font-bold text-warning-400">{systemInfo.num_active_executions}</span>
						</div>
						<div class="flex justify-between items-center text-[10px]">
							<span class="text-surface-400">Events Processed</span>
							<span class="font-bold text-success-400">{systemInfo.total_events}</span>
						</div>
						<div class="pt-1 mt-1 border-t border-surface-800/50">
							<p class="text-[9px] text-surface-500 font-mono truncate" title={systemInfo.server_url}>
								{systemInfo.server_url}
							</p>
						</div>
					</div>
				{:else}
					<p class="text-[10px] text-error-400 italic">Server unreachable</p>
				{/if}
			</div>
		</aside>

		<!-- Pane 2: Multi-tab Workspace (L1 background, holds L2/L3) -->
		<main class="flex-auto min-w-0 h-full flex flex-col bg-surface-950 relative">
			<!-- Workspace Content Area -->
			<div class="flex-auto overflow-y-auto p-4 flex flex-col gap-4">
				{@render children()}
			</div>
		</main>
	</div>
</div>
