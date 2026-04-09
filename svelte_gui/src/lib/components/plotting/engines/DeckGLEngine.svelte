<script lang="ts">
import type { Layer } from "@deck.gl/core";
import { Deck } from "@deck.gl/core";
import { onDestroy, onMount, type Snippet } from "svelte";

interface Props {
	layers: Layer[];
	// biome-ignore lint/suspicious/noExplicitAny: Deck.gl view state type is complex
	initialViewState?: any;
	// biome-ignore lint/suspicious/noExplicitAny: Deck.gl view type is complex
	views?: any;
	children?: Snippet;
}

let {
	layers,
	initialViewState = { longitude: 0, latitude: 0, zoom: 1 },
	views,
	// biome-ignore lint/correctness/noUnusedVariables: used in HTML template
	children,
}: Props = $props();
let container: HTMLCanvasElement;
let deckInstance: Deck | null = null;

onMount(() => {
	if (container) {
		// biome-ignore lint/suspicious/noExplicitAny: Deck.gl config dynamic building
		const deckConfig: any = {
			canvas: container,
			initialViewState,
			controller: true,
			layers,
			useDevicePixels: true,
		};
		if (views) deckConfig.views = views;
		deckInstance = new Deck(deckConfig);
	}
});

onDestroy(() => {
	if (deckInstance) {
		deckInstance.finalize();
	}
});

// React to layer updates
$effect(() => {
	if (deckInstance) {
		deckInstance.setProps({ layers });
	}
});
</script>

<div class="relative w-full h-full min-h-[300px] overflow-hidden rounded">
	<!-- DeckGL expects an absolute positioned canvas filling its container -->
	<canvas bind:this={container} class="absolute inset-0 w-full h-full bg-surface-950"></canvas>

	<!-- Floating controls or legend could go here, layered above the canvas -->
	{#if children}
		{@render children()}
	{/if}
</div>
