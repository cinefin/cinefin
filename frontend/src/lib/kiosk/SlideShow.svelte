<script lang="ts">
	import { fade } from 'svelte/transition';
	import Slide from './Slide.svelte';
	import type { KioskController } from './controller.svelte';
	import type { KioskFilm } from './types';

	interface Props {
		kiosk: KioskController;
		films: KioskFilm[];
		compact?: boolean;
	}
	let { kiosk, films, compact = false }: Props = $props();

	const FADE_MS = 900;

	let index = $state(0);
	const dwellMs = $derived(kiosk.prefs.spotlightSecs * 1000);
	// Depend on value-stable keys, never `films` itself: the arrays get fresh identity per poll/tick.
	const filmsKey = $derived(films.map((f) => f.id).join(','));
	const count = $derived(films.length);

	$effect(() => {
		void filmsKey; // retrack: a new bill restarts from slide 0
		index = 0;
		if (count <= 1) return;
		const timer = setInterval(() => {
			index = (index + 1) % films.length;
		}, dwellMs);
		return () => clearInterval(timer);
	});

	const film = $derived(films[Math.min(index, films.length - 1)]);
</script>

{#if film}
	{#key `${filmsKey}:${index}`}
		<div class="slide-host" in:fade={{ duration: FADE_MS }} out:fade={{ duration: FADE_MS }}>
			<Slide {kiosk} {film} {index} total={films.length} {compact} {dwellMs} />
		</div>
	{/key}
{/if}
