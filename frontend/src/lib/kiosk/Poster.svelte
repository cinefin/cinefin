<script lang="ts">
	import type { KioskFilmish } from './types';

	let { film = null, cls = '' }: { film?: KioskFilmish | null; cls?: string } = $props();

	let failedSrc = $state<string | null>(null);
	const missing = $derived(!film?.poster || failedSrc === film.poster);
</script>

<div class="poster {cls}" class:poster-missing={missing}>
	{#if film?.poster && !missing}
		<img src={film.poster} alt="" onerror={() => (failedSrc = film?.poster ?? null)} />
	{/if}
	<span class="poster-fallback"><em>{film?.title ?? ''}</em></span>
</div>
