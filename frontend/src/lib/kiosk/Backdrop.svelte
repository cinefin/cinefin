<script lang="ts">
	import type { KioskFilmish } from './types';

	interface Props {
		film?: KioskFilmish | null;
	}
	let { film = null }: Props = $props();

	let failedSrc = $state<string | null>(null);
</script>

<div class="slide-backdrop">
	{#if film?.poster && failedSrc !== film.poster}
		<img src={film.poster} alt="" onerror={() => (failedSrc = film?.poster ?? null)} />
	{/if}
</div>
