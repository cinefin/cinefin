<script lang="ts">
	import { clock } from './format';
	import type { Kiosk } from './kiosk.svelte';

	let { kiosk, quiet = false }: { kiosk: Kiosk; quiet?: boolean } = $props();
	const h12 = $derived(kiosk.cinema?.time_format === '12h');
</script>

<header class:quiet>
	{#if kiosk.cinema?.logo_url}
		<img src={kiosk.cinema.logo_url} alt={kiosk.cinema.name} />
	{:else}
		<span class="name">{kiosk.cinema?.name ?? 'Cinefin'}</span>
	{/if}
	{#if kiosk.settings?.clock}
		<span class="time now">{clock(kiosk.now, h12)}</span>
		{#if !quiet}
			<span class="muted date"
				>{new Date(kiosk.now).toLocaleDateString('en-GB', {
					weekday: 'long',
					day: 'numeric',
					month: 'long'
				})}</span
			>
		{/if}
	{/if}
</header>

<style>
	header {
		position: relative;
		display: flex;
		align-items: baseline;
		gap: 18px;
		font-size: 44px;
	}
	.quiet {
		font-size: 36px;
		color: var(--color-muted);
	}
	img {
		height: 56px;
		align-self: center;
	}
	.now {
		margin-left: auto;
		line-height: 1;
	}
	.date {
		font-size: 22px;
	}
</style>
