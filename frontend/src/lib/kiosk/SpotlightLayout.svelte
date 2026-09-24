<script lang="ts">
	import KioskEmpty from './KioskEmpty.svelte';
	import SlideShow from './SlideShow.svelte';
	import type { KioskController } from './controller.svelte';

	interface Props {
		kiosk: KioskController;
	}
	let { kiosk }: Props = $props();

	const films = $derived(kiosk.films.length ? kiosk.films : kiosk.screeningFilms());
</script>

{#if !films.length}
	<KioskEmpty title="Nothing on the marquee" sub="Check back soon for upcoming showings" />
{:else}
	<div class="spotlight">
		<SlideShow {kiosk} {films} />
	</div>
{/if}
