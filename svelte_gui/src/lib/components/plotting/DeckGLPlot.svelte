<script lang="ts">
import { onMount, onDestroy } from "svelte";
import { Deck, OrthographicView } from "@deck.gl/core";
import { GridCellLayer } from "@deck.gl/layers";

interface Props {
	data: any[]; // e.g. [{realization: 0, values: [..]}, {realization: 1, values: [..]}]
	valueRange?: [number, number];
}

let { data, valueRange }: Props = $props();

let container: HTMLDivElement;
let deck: any = undefined;

let layerData = $derived.by(() => {
	if (!data || data.length === 0) return [];

	// Assume we are plotting realization 0 for now
	const values = data[0].values;
	const n = values.length;
	const dim = Math.round(Math.sqrt(n));

	const points = [];
	for (let i = 0; i < n; i++) {
		const y = Math.floor(i / dim);
		const x = i % dim;
		const val = values[i];
		points.push({ x, y, value: val });
	}
	return points;
});

$effect(() => {
	if (deck && layerData) {
		const layer = new GridCellLayer({
			id: "grid-cell-layer",
			data: layerData,
			pickable: true,
			extruded: false,
			cellSize: 1,
			getPosition: (d: any) => [d.x, d.y],
			getFillColor: (d: any) => {
				const v = d.value;
				const [min, max] = valueRange || [0, 100];
				const range = max - min || 1;
				const norm = Math.min(Math.max((v - min) / range, 0), 1);
				return [255 * norm, 0, 255 * (1 - norm), 255];
			}
		});

		deck.setProps({
			layers: [layer]
		});
	}
});

onMount(() => {
	if (container) {
		const dim = layerData.length > 0 ? Math.round(Math.sqrt(layerData.length)) : 100;
		deck = new Deck({
			parent: container,
			views: [new OrthographicView({ id: "ortho" })],
			initialViewState: {
				target: [dim / 2, dim / 2, 0] as [number, number, number],
				zoom: 3
			} as any,
			controller: true,
			layers: []
		});
	}
});

onDestroy(() => {
	if (deck) {
		deck.finalize();
	}
});
</script>

<div bind:this={container} class="relative w-full h-full bg-surface-950 rounded border border-surface-700 overflow-hidden">
	<div class="absolute top-2 left-2 bg-surface-900/80 px-2 py-1 rounded border border-surface-700 text-xs font-mono z-10 pointer-events-none">
		Deck.GL 2D Grid Map (Realization 0 preview)
	</div>
</div>
