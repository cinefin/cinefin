<script lang="ts">
	// Night hours, or nothing to show: the name and the time, dimmed at night.
	import type { Kiosk } from './kiosk.svelte';

	let { kiosk, dim = false }: { kiosk: Kiosk; dim?: boolean } = $props();
</script>

<div class="scene pad" class:dim>
	<div class="centre">
		<div class="name">{kiosk.cinema?.name ?? 'Cinefin'}</div>
		{#if kiosk.settings?.clock}<div class="time">{kiosk.time(kiosk.now)}</div>{/if}
		{#if !dim}<div class="muted">No screenings booked</div>{/if}
	</div>
</div>

<style>
	.scene {
		background: var(--color-bg);
	}
	.centre {
		margin: auto;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 36px;
		font-size: 30px;
	}
	.name {
		font-size: 72px;
	}
	.time {
		font-size: 120px;
		line-height: 1;
	}
	.dim .centre {
		opacity: 0.3;
	}
</style>
