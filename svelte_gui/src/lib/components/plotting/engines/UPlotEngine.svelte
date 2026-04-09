<script lang="ts">
import { onDestroy, onMount } from "svelte";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";

interface Props {
	data: uPlot.AlignedData;
	opts: uPlot.Options;
}

let { data, opts }: Props = $props();

let chartContainer: HTMLElement;
let uplotInst: uPlot | null = null;
let resizeObserver: ResizeObserver;

onMount(() => {
	if (chartContainer) {
		uplotInst = new uPlot(opts, data, chartContainer);

		// Handle responsive resizing
		resizeObserver = new ResizeObserver((entries) => {
			for (const entry of entries) {
				if (uplotInst) {
					uplotInst.setSize({
						width: entry.contentRect.width,
						height: entry.contentRect.height,
					});
				}
			}
		});
		resizeObserver.observe(chartContainer);
	}
});

onDestroy(() => {
	if (resizeObserver) resizeObserver.disconnect();
	if (uplotInst) uplotInst.destroy();
});

// React to data or options changes
$effect(() => {
	if (uplotInst) {
		uplotInst.setData(data);
	}
});
</script>

<div bind:this={chartContainer} class="w-full h-full min-h-[250px] uplot-dark"></div>

<style>
	/* Skeleton/Tailwind integration for uPlot */
	:global(.uplot-dark .u-title) {
		color: var(--color-surface-100);
		font-family: var(--font-mono);
		font-size: 14px;
	}
	:global(.uplot-dark .u-axis text) {
		fill: var(--color-surface-400);
		font-family: var(--font-mono);
	}
	:global(.uplot-dark .u-legend) {
		color: var(--color-surface-300);
		font-family: var(--font-mono);
		font-size: 12px;
	}
</style>
