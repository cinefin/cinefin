<script lang="ts">
	import Poster from './Poster.svelte';
	import type { KioskFilmish } from './types';

	interface Props {
		films: KioskFilmish[];
		cls?: string;
	}
	let { films, cls = '' }: Props = $props();
</script>

{#if films.length <= 1}
	<Poster film={films[0] ?? null} {cls} />
{:else}
	<div class="poster-multi n{Math.min(films.length, 3)} {cls}">
		{#each films.slice(0, 3) as film (film.id ?? film.title)}
			<Poster {film} />
		{/each}
	</div>
{/if}
