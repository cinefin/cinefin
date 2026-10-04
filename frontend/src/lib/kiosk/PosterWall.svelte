<script lang="ts">
	// ?mode=posters: the kiosk's films, one full-screen poster at a time, nothing else.
	import { fade } from 'svelte/transition';
	import type { Kiosk } from './kiosk.svelte';

	let { kiosk }: { kiosk: Kiosk } = $props();

	const films = $derived(kiosk.turnFilms.filter((f) => f.poster));
	const film = $derived(kiosk.pick(films));

	$effect(() => {
		const next = films.length > 1 ? films[(kiosk.turn + 1) % films.length] : null;
		if (next?.poster) new Image().src = next.poster;
	});
</script>

{#if film}
	{#key film.id}
		<img src={film.poster} alt="" in:fade={{ duration: 1200 }} out:fade={{ duration: 1200 }} />
	{/key}
{/if}

<style>
	img {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		object-fit: cover;
	}
</style>
