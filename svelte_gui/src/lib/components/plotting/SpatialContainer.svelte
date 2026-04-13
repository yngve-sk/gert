<script lang="ts">
import { OrbitView } from "@deck.gl/core";
import { PointCloudLayer } from "@deck.gl/layers";
import { onMount } from "svelte";
// biome-ignore lint/correctness/noUnusedImports: used in HTML template
import DeckGLEngine from "./engines/DeckGLEngine.svelte";

// We generate a dummy 3D point cloud to verify the WebGL engine works
// as required by M11, since the raw parameter matrix doesn't inherently
// possess x,y,z spatial fields without an explicit reservoir geometry map.
// biome-ignore lint/suspicious/noExplicitAny: Dummy data type
let pointCloudData = $state<any[]>([]);

onMount(() => {
	const data = [];
	for (let i = 0; i < 10000; i++) {
		data.push({
			position: [
				(Math.random() - 0.5) * 100,
				(Math.random() - 0.5) * 100,
				(Math.random() - 0.5) * 20,
			],
			color: [
				Math.floor(Math.random() * 255),
				Math.floor(Math.random() * 255),
				255,
			],
		});
	}
	pointCloudData = data;
});

// biome-ignore lint/correctness/noUnusedVariables: passed to engine
let layers = $derived([
	new PointCloudLayer({
		id: "point-cloud-layer",
		data: pointCloudData,
		// biome-ignore lint/suspicious/noExplicitAny: layer accessor
		getPosition: (d: any) => d.position,
		getNormal: [0, 1, 0],
		// biome-ignore lint/suspicious/noExplicitAny: layer accessor
		getColor: (d: any) => d.color,
		pointSize: 2,
	}),
]);

// Use OrbitView for 3D exploration instead of standard 2D MapView
// biome-ignore lint/correctness/noUnusedVariables: passed to engine
const initialViewState = {
	target: [0, 0, 0],
	zoom: 2,
	rotationX: 45,
	rotationOrbit: 30,
};
// biome-ignore lint/correctness/noUnusedVariables: passed to engine
const views = [new OrbitView({ id: "3d-view", controller: true })];

// Ensure we pass the view config correctly
// Note: We need to override the default MapView in Deck by passing views if we want 3D
</script>

<div class="w-full h-full flex flex-col relative">
	{#if pointCloudData.length === 0}
		<div class="flex-auto flex items-center justify-center">
			<span class="text-surface-500 italic text-sm">Generating 3D spatial field...</span>
		</div>
	{:else}
		<DeckGLEngine {layers} {initialViewState} {views}>
			<div class="absolute top-4 left-4 bg-surface-900/80 p-3 rounded border border-surface-700 shadow-xl pointer-events-none">
				<h3 class="text-[10px] uppercase font-bold tracking-widest text-primary-400">WebGL Spatial Engine</h3>
				<div class="text-xs text-surface-300 font-mono mt-1">{pointCloudData.length} points</div>
				<div class="text-[10px] text-surface-500 mt-2 italic">Drag to rotate • Scroll to zoom</div>
			</div>
		</DeckGLEngine>
	{/if}
</div>
