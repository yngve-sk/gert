<script lang="ts">
import { onDestroy, onMount } from "svelte";

interface Props {
	experimentId: string;
	executionId: string;
	isRunning: boolean;
}

let { experimentId, executionId, isRunning }: Props = $props();

let logs: string[] = $state([]);
let terminalElement: HTMLElement;
let abortController: AbortController | null = null;
let isAutoScroll = $state(true);

// In a true virtualized setup, we would limit the rendered DOM nodes.
// For this M8 implementation, we limit the array length to 1000 lines.
const MAX_LINES = 1000;

export function connectStream() {
	if (abortController) {
		return; // already connected
	}

	abortController = new AbortController();

	if (isRunning) {
		fetch("/api/logs/stream", {
			signal: abortController.signal,
		})
			.then(async (response) => {
				if (!response.body) {
					logs = [
						...logs,
						"[Terminal Error] ReadableStream not supported or no body.",
					];
					return;
				}

				const reader = response.body.getReader();
				const decoder = new TextDecoder("utf-8");
				let buffer = "";

				while (true) {
					const { done, value } = await reader.read();
					if (done) break;

					buffer += decoder.decode(value, { stream: true });

					// SSE data comes in as "data: line\n\n"
					const chunks = buffer.split("\n\n");
					// The last element is the incomplete buffer
					buffer = chunks.pop() || "";

					let newLines: string[] = [];
					for (const chunk of chunks) {
						if (chunk.startsWith("data: ")) {
							newLines.push(chunk.substring(6));
						}
					}

					if (newLines.length > 0) {
						logs = [...logs, ...newLines].slice(-MAX_LINES);
						if (isAutoScroll) {
							// use requestAnimationFrame to allow DOM to update before scrolling
							requestAnimationFrame(() => {
								if (terminalElement) {
									terminalElement.scrollTop = terminalElement.scrollHeight;
								}
							});
						}
					}
				}
			})
			.catch((err) => {
				if (err.name !== "AbortError") {
					console.error("Log stream error:", err);
					logs = [...logs, `[Terminal Error] Connection lost: ${err.message}`];
				}
			});
	} else {
		// Static fetch
		fetch(`/api/experiments/${experimentId}/executions/${executionId}/logs`, {
			signal: abortController.signal,
		})
			.then(async (response) => {
				if (!response.ok) {
					const text = await response.text();
					logs = [`[Terminal Error] Failed to fetch logs: ${response.statusText} - ${text}`];
					return;
				}
				const text = await response.text();
				logs = text.split("\n").slice(-MAX_LINES);
				if (isAutoScroll) {
					requestAnimationFrame(() => {
						if (terminalElement) {
							terminalElement.scrollTop = terminalElement.scrollHeight;
						}
					});
				}
			})
			.catch((err) => {
				if (err.name !== "AbortError") {
					console.error("Log fetch error:", err);
					logs = [`[Terminal Error] Failed to fetch logs: ${err.message}`];
				}
			});
	}
}

export function disconnectStream() {
	if (abortController) {
		abortController.abort();
		abortController = null;
	}
}

// biome-ignore lint/correctness/noUnusedVariables: used in template
function handleScroll() {
	if (!terminalElement) return;
	// If user scrolls up, disable auto-scroll. If they scroll to bottom, re-enable.
	const isAtBottom =
		terminalElement.scrollHeight - terminalElement.scrollTop <=
		terminalElement.clientHeight + 10;
	isAutoScroll = isAtBottom;
}

onMount(() => {
	connectStream();
});

onDestroy(() => {
	disconnectStream();
});
</script>

<div class="flex flex-col h-full w-full bg-surface-950 border border-surface-700 rounded overflow-hidden shadow-inner">
	<header class="flex-none bg-surface-800 border-b border-surface-700 p-2 flex justify-between items-center">
		<div class="flex items-center gap-2">
			<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-surface-400" viewBox="0 0 20 20" fill="currentColor">
				<path fill-rule="evenodd" d="M2 5a2 2 0 012-2h12a2 2 0 012 2v10a2 2 0 01-2 2H4a2 2 0 01-2-2V5zm3.293 1.293a1 1 0 011.414 0l3 3a1 1 0 010 1.414l-3 3a1 1 0 01-1.414-1.414L7.586 10 5.293 7.707a1 1 0 010-1.414zM11 12a1 1 0 100 2h3a1 1 0 100-2h-3z" clip-rule="evenodd" />
			</svg>
			<span class="text-xs font-bold text-surface-300 uppercase tracking-wider">{isRunning ? 'Live Log Stream' : 'Static Logs'}</span>
		</div>
		<div class="flex items-center gap-2">
			{#if !isAutoScroll}
				<span class="text-[10px] text-warning-500 font-bold bg-warning-500/10 px-2 py-0.5 rounded">Auto-scroll Paused</span>
			{/if}
			<button
				class="text-[10px] uppercase font-bold text-surface-400 hover:text-surface-100 transition-colors"
				onclick={() => { logs = []; }}
			>
				Clear
			</button>
		</div>
	</header>

	<div
		bind:this={terminalElement}
		onscroll={handleScroll}
		class="flex-auto overflow-y-auto p-3 font-mono text-[11px] leading-tight text-surface-300"
	>
		{#if logs.length === 0}
			<div class="text-surface-500 italic">{isRunning ? 'Connecting to /api/logs/stream...' : 'Loading logs...'}</div>
		{:else}
			{#each logs as log (log)}
				<div class="whitespace-pre-wrap break-words">{log}</div>
			{/each}
		{/if}
	</div>
</div>
