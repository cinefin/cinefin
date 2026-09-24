<script lang="ts">
	import KioskEmpty from './KioskEmpty.svelte';
	import NnRow from './NnRow.svelte';
	import SlideShow from './SlideShow.svelte';
	import type { KioskController } from './controller.svelte';

	interface Props {
		kiosk: KioskController;
	}
	let { kiosk }: Props = $props();

	const films = $derived(kiosk.films.length ? kiosk.films : kiosk.screeningFilms());
	const screenings = $derived(kiosk.activeScreenings.slice(0, 8));
</script>

{#if !films.length && !screenings.length}
	<KioskEmpty title="Nothing on the marquee" sub="Check back soon for upcoming showings" />
{:else}
	<div class="split">
		<section class="split-hero">
			{#if films.length}
				<SlideShow {kiosk} {films} compact />
			{:else}
				<KioskEmpty
					title="Nothing on the marquee"
					sub="Films appear here once flagged for the kiosk"
				/>
			{/if}
		</section>
		<aside class="split-rail">
			<div class="rail-title">Showings</div>
			<div class="rail-items">
				{#if screenings.length}
					{#each screenings as screening (screening.id)}
						<NnRow {kiosk} {screening} />
					{/each}
				{:else}
					<div class="rail-none">No showings scheduled</div>
				{/if}
			</div>
		</aside>
	</div>
{/if}
