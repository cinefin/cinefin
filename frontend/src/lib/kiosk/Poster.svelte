<script lang="ts">
	import type { KioskFilm } from './kiosk.svelte';

	let {
		film,
		class: cls = '',
		style = '',
		grain = false
	}: { film: Partial<KioskFilm>; class?: string; style?: string; grain?: boolean } = $props();

	let failed = $state(false);
</script>

<div class="poster {cls}" class:film-grain={grain} {style}>
	{#if film.poster && !failed}
		<img src={film.poster} alt="" onerror={() => (failed = true)} />
	{:else}
		<span>{film.title}</span>
	{/if}
</div>

<style>
	.poster {
		position: relative;
		overflow: hidden;
		flex: none;
		aspect-ratio: 2 / 3;
		container-type: inline-size;
		display: flex;
		align-items: flex-end;
		box-sizing: border-box;
		padding: 7%;
		background: var(--color-surface-2);
		border: 1px solid var(--color-border);
	}
	.poster::before,
	.poster::after {
		z-index: 1;
	}
	img {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		object-fit: cover;
	}
	span {
		font-family: var(--font-display);
		font-size: 14cqw;
		line-height: 1;
		color: var(--color-muted);
	}
</style>
