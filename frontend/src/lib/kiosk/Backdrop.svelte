<script lang="ts">
	// The poster's own colour, washed behind the scene.
	import type { KioskFilm } from './kiosk.svelte';

	let { film, side = 'right' }: { film?: Partial<KioskFilm>; side?: 'left' | 'right' } = $props();
</script>

<div class="backdrop {side}" aria-hidden="true">
	{#if film?.poster}<img src={film.poster} alt="" />{/if}
</div>

<style>
	.backdrop {
		position: absolute;
		inset: 0;
		overflow: hidden;
		background: var(--color-bg);
	}
	img {
		position: absolute;
		top: -10%;
		width: 60%;
		height: 120%;
		object-fit: cover;
		filter: blur(110px) saturate(1.2);
		opacity: 0.4;
	}
	.right img {
		right: -5%;
	}
	.left img {
		left: -5%;
	}
	.backdrop::after {
		content: '';
		position: absolute;
		inset: 0;
		background: linear-gradient(
			90deg,
			var(--color-bg) 25%,
			color-mix(in oklab, var(--color-bg) 55%, transparent) 70%,
			color-mix(in oklab, var(--color-bg) 30%, transparent)
		);
	}
	.left::after {
		background: linear-gradient(
			270deg,
			var(--color-bg) 25%,
			color-mix(in oklab, var(--color-bg) 55%, transparent) 70%,
			color-mix(in oklab, var(--color-bg) 30%, transparent)
		);
	}
</style>
