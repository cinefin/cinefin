<script lang="ts">
	// One poster, or the first two of a bill overlapping.
	import Poster from './Poster.svelte';
	import type { KioskFilm } from './kiosk.svelte';

	let { films, width }: { films: Partial<KioskFilm>[]; width: number } = $props();
	const grain = $derived(width >= 300);
</script>

{#if films.length > 1}
	<div class="pair" style="width: {width}px; height: {width * 1.5}px">
		<Poster
			film={films[0]}
			{grain}
			style="position: absolute; left: 0; top: 0; width: 72%; z-index: 1"
		/>
		<Poster
			film={films[1]}
			style="position: absolute; right: 0; top: 7%; width: 64%; opacity: .7"
		/>
	</div>
{:else if films.length}
	<Poster film={films[0]} {grain} style="width: {width}px" />
{/if}

<style>
	.pair {
		position: relative;
		flex: none;
	}
</style>
