<script lang="ts">
import { onDestroy, untrack } from "svelte";

interface Props {
	experimentId: string;
	executionId: string;
	isRunning: boolean;
}

let { experimentId, executionId, isRunning }: Props = $props();

let rawLogs: string[] = $state([]);
let terminalElement: HTMLElement | undefined;
let abortController: AbortController | null = null;
let isAutoScroll = $state(true);
let streamRetryTimeout: number | undefined;

let showDebug = $state(true);
let showInfo = $state(true);
let showWarning = $state(true);
let showError = $state(true);
let searchQuery = $state("");

const MAX_LINES = 1000;

let filteredLogs = $derived.by(() => {
	const query = searchQuery.toUpperCase();
	return rawLogs.filter(log => {
		const upperLog = log.toUpperCase();

		const isDebug = upperLog.includes("[DEBUG]");
		const isInfo = upperLog.includes("[INFO]");
		const isWarn = upperLog.includes("[WARN");
		const isError = upperLog.includes("[ERROR]") || upperLog.includes("[CRITICAL]");

		let keep = true;
		if (isDebug && !showDebug) keep = false;
		else if (isInfo && !showInfo) keep = false;
		else if (isWarn && !showWarning) keep = false;
		else if (isError && !showError) keep = false;

		if (!keep) return false;

		if (query && !upperLog.includes(query)) {
			return false;
		}

		return true;
	});
});

function scrollDown() {
	if (isAutoScroll && terminalElement) {
		requestAnimationFrame(() => {
			if (terminalElement) {
				terminalElement.scrollTop = terminalElement.scrollHeight;
			}
		});
	}
}

async function connectStream() {
	if (abortController) {
		abortController.abort();
	}
	abortController = new AbortController();

	if (streamRetryTimeout) {
		clearTimeout(streamRetryTimeout);
	}

	if (isRunning) {
		try {
			console.log("[Terminal] Connecting to SSE stream...");
			const response = await fetch(`/experiments/${experimentId}/executions/${executionId}/logs/stream`, {
				headers: {
					"Accept": "text/event-stream",
				},
				signal: abortController.signal,
			});

			if (!response.ok) {
				console.error("[Terminal] SSE stream failed:", response.status, response.statusText);
				rawLogs = [...rawLogs, `[Terminal Error] Failed to connect: ${response.statusText}`];
				scheduleRetry();
				return;
			}

			if (!response.body) {
				rawLogs = [...rawLogs, "[Terminal Error] ReadableStream not supported."];
				return;
			}

			console.log("[Terminal] SSE stream connected.");
			const reader = response.body.getReader();
			const decoder = new TextDecoder("utf-8");
			let buffer = "";

			while (true) {
				const { done, value } = await reader.read();
				if (done) {
					console.log("[Terminal] SSE stream reader done.");
					break;
				}

				buffer += decoder.decode(value, { stream: true });
				const chunks = buffer.split("\n\n");
				buffer = chunks.pop() || "";

				const newLines: string[] = [];
				for (const chunk of chunks) {
					if (chunk.startsWith("data: ")) {
						newLines.push(chunk.substring(6));
					}
				}

				if (newLines.length > 0) {
					rawLogs = [...rawLogs, ...newLines].slice(-MAX_LINES);
					scrollDown();
				}
			}

			// Stream ended naturally
			if (isRunning) {
				rawLogs = [...rawLogs, "[Terminal] Stream ended. Reconnecting..."];
				scheduleRetry();
			}
		} catch (err: unknown) {
			if (err instanceof Error && err.name !== "AbortError") {
				console.error("Log stream error:", err);
				rawLogs = [...rawLogs, `[Terminal Error] Connection lost: ${err.message}`];
				scheduleRetry();
			}
		}
	} else {
		// Static fetch
		try {
			const response = await fetch(
				`/experiments/${experimentId}/executions/${executionId}/logs`,
				{
					signal: abortController.signal,
				}
			);

			if (!response.ok) {
				const text = await response.text();
				rawLogs = [`[Terminal Error] Failed to fetch logs: ${response.statusText} - ${text}`];
				return;
			}

			const text = await response.text();
			rawLogs = text.split("\n").slice(-MAX_LINES);
			scrollDown();
		} catch (err: unknown) {
			if (err instanceof Error && err.name !== "AbortError") {
				console.error("Log fetch error:", err);
				rawLogs = [`[Terminal Error] Failed to fetch logs: ${err.message}`];
			}
		}
	}
}

function scheduleRetry() {
	if (isRunning && !abortController?.signal.aborted) {
		streamRetryTimeout = window.setTimeout(() => {
			connectStream();
		}, 3000);
	}
}

function disconnectStream() {
	if (streamRetryTimeout) {
		clearTimeout(streamRetryTimeout);
	}
	if (abortController) {
		abortController.abort();
		abortController = null;
	}
}

function handleScroll() {
	if (!terminalElement) return;
	const isAtBottom =
		terminalElement.scrollHeight - terminalElement.scrollTop <=
		terminalElement.clientHeight + 10;
	isAutoScroll = isAtBottom;
}

$effect(() => {
	// Re-run connection logic only if these reactive props change
	const _running = isRunning;
	const _expId = experimentId;
	const _execId = executionId;

	untrack(() => {
		connectStream();
	});

	// Cleanup on effect re-run or unmount
	return () => {
		untrack(() => {
			disconnectStream();
		});
	};
});
</script>

<div class="flex flex-col h-full w-full bg-surface-950 border border-surface-700 rounded overflow-hidden shadow-inner">
	<header class="flex-none bg-surface-800 border-b border-surface-700 p-2 flex flex-col sm:flex-row gap-2 justify-between items-start sm:items-center">
		<div class="flex items-center gap-2">
			<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-surface-400" viewBox="0 0 20 20" fill="currentColor">
				<path fill-rule="evenodd" d="M2 5a2 2 0 012-2h12a2 2 0 012 2v10a2 2 0 01-2 2H4a2 2 0 01-2-2V5zm3.293 1.293a1 1 0 011.414 0l3 3a1 1 0 010 1.414l-3 3a1 1 0 01-1.414-1.414L7.586 10 5.293 7.707a1 1 0 010-1.414zM11 12a1 1 0 100 2h3a1 1 0 100-2h-3z" clip-rule="evenodd" />
			</svg>
			<span class="text-xs font-bold text-surface-300 uppercase tracking-wider">{isRunning ? 'Live Log Stream' : 'Static Logs'}</span>
		</div>
		<div class="flex flex-wrap items-center gap-2">
			<input
				type="text"
				bind:value={searchQuery}
				placeholder="Search logs..."
				class="bg-surface-900 border border-surface-700 rounded px-2 py-0.5 text-[10px] text-surface-200 outline-none focus:border-primary-500 w-32 transition-colors"
			/>
			<div class="flex items-center rounded border border-surface-700 overflow-hidden text-[9px] font-bold">
				<button class="px-2 py-1 {showDebug ? 'bg-surface-600 text-surface-100' : 'bg-surface-800 text-surface-500'} transition-colors" onclick={() => showDebug = !showDebug}>DEBUG</button>
				<button class="px-2 py-1 border-l border-surface-700 {showInfo ? 'bg-primary-600/30 text-primary-300' : 'bg-surface-800 text-surface-500'} transition-colors" onclick={() => showInfo = !showInfo}>INFO</button>
				<button class="px-2 py-1 border-l border-surface-700 {showWarning ? 'bg-warning-600/30 text-warning-300' : 'bg-surface-800 text-surface-500'} transition-colors" onclick={() => showWarning = !showWarning}>WARN</button>
				<button class="px-2 py-1 border-l border-surface-700 {showError ? 'bg-error-600/30 text-error-300' : 'bg-surface-800 text-surface-500'} transition-colors" onclick={() => showError = !showError}>ERR</button>
			</div>
			{#if !isAutoScroll}
				<span class="text-[10px] text-warning-500 font-bold bg-warning-500/10 px-2 py-0.5 rounded">Paused</span>
			{/if}
			<button
				class="text-[10px] uppercase font-bold text-surface-400 hover:text-surface-100 transition-colors ml-1"
				onclick={() => { rawLogs = []; }}
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
		{#if rawLogs.length === 0}
			<div class="text-surface-500 italic">{isRunning ? 'Connecting to /logs/stream...' : 'Loading logs...'}</div>
		{:else if filteredLogs.length === 0}
			<div class="text-surface-500 italic">No logs match the current filters.</div>
		{:else}
			{#each filteredLogs as log}
				<div class="whitespace-pre-wrap break-words">{log}</div>
			{/each}
		{/if}
	</div>
</div>
