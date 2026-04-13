<script lang="ts">
import { onMount, onDestroy } from "svelte";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";

interface Props {
	options: uPlot.Options;
	data: uPlot.AlignedData;
}

let { options, data }: Props = $props();
let container: HTMLElement | undefined;
let chart: uPlot | undefined;

$effect(() => {
	if (container && data) {
		if (chart) {
			chart.destroy();
		}
		chart = new uPlot(options, data, container);
	}

	return () => {
		if (chart) {
			chart.destroy();
			chart = undefined;
		}
	};
});
</script>

<div bind:this={container} class="uplot-wrapper inline-block"></div>
