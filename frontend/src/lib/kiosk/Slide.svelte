<script lang="ts">
	import Backdrop from './Backdrop.svelte';
	import MetaRow from './MetaRow.svelte';
	import Poster from './Poster.svelte';
	import type { KioskController } from './controller.svelte';
	import { dayLabel, fmtClock } from './time';
	import type { KioskFilm } from './types';

	interface Props {
		kiosk: KioskController;
		film: KioskFilm;
		index: number;
		total: number;
		compact?: boolean;
		dwellMs: number;
	}
	let { kiosk, film, index, total, compact = false, dwellMs }: Props = $props();

	const showtime = $derived(kiosk.showtimeFor(film));
	const num = (i: number) => String(i).padStart(2, '0');
</script>

<div class="slide" class:compact class:kb-b={index % 2 === 1}>
	<Backdrop {film} />
	<div class="slide-inner">
		<Poster {film} cls="slide-poster" />
		<div class="slide-body">
			<div class="eyebrow">Now Showing</div>
			<h1 class="slide-title">{film.title}</h1>
			<MetaRow {film} />
			{#if film.genres?.length}
				<div class="genres">
					{#each film.genres as genre, i (genre)}
						{#if i}<i class="dot"></i>{/if}{genre}
					{/each}
				</div>
			{/if}
			{#if film.synopsis}
				<p class="synopsis">{film.synopsis}</p>
			{/if}
			{#if showtime}
				<div class="showtime">
					<span class="showtime-plate">{dayLabel(showtime.start)} {fmtClock(showtime.start)}</span>
					<span class="showtime-name">{showtime.programme}</span>
				</div>
			{/if}
		</div>
	</div>
	<div class="slide-progress">
		<span class="bar"><i style="animation-duration:{dwellMs}ms"></i></span>
		<em>{num(index + 1)} / {num(total)}</em>
	</div>
</div>
