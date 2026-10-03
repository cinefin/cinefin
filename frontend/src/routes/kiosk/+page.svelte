<script lang="ts">
	import { fade } from 'svelte/transition';
	import { KioskController } from '$lib/kiosk/controller.svelte';
	import BoardLayout from '$lib/kiosk/BoardLayout.svelte';
	import CountdownTakeover from '$lib/kiosk/CountdownTakeover.svelte';
	import Picker from '$lib/kiosk/Picker.svelte';
	import PlayoutTakeover from '$lib/kiosk/PlayoutTakeover.svelte';
	import SplitLayout from '$lib/kiosk/SplitLayout.svelte';
	import SpotlightLayout from '$lib/kiosk/SpotlightLayout.svelte';
	import TonightLayout from '$lib/kiosk/TonightLayout.svelte';
	import WallLayout from '$lib/kiosk/WallLayout.svelte';
	import './kiosk.css';
	import { onMount } from 'svelte';

	const kiosk = new KioskController();

	// onMount, NOT $effect: init() reads reactive prefs the first payload rewrites, which
	// inside an $effect would re-run it and destroy the controller mid-boot (blank stage).
	onMount(() => {
		kiosk.init();
		return () => kiosk.destroy();
	});

	let cursorOn = $state(false);

	const MODE_FADE_MS = 450;
	const LAYOUT_VIEWS: Record<string, typeof WallLayout> = {
		spotlight: SpotlightLayout,
		split: SplitLayout,
		board: BoardLayout,
		tonight: TonightLayout
	};
	const Layout = $derived(LAYOUT_VIEWS[kiosk.effectiveLayout] ?? WallLayout);

	// One key for "what the stage shows": a change crossfades the scene.
	const stageKey = $derived(
		{
			playout: `playout:${kiosk.playoutKey}`,
			countdown: `countdown:${kiosk.countdownTarget?.id ?? 0}`,
			night: 'night',
			layout: `layout:${kiosk.effectiveLayout}`
		}[kiosk.mode]
	);

	const title = $derived(
		kiosk.cinema?.name && kiosk.cinema.name !== 'Cinefin'
			? `Now Showing - ${kiosk.cinema.name}`
			: 'Now Showing'
	);
	const accentStyle = $derived(
		kiosk.cinema?.accent_color ? `--color-accent:${kiosk.cinema.accent_color}` : undefined
	);
</script>

<svelte:head>
	<title>{title}</title>
</svelte:head>

<div
	class="kiosk-root"
	class:asleep={kiosk.mode === 'night'}
	class:no-header={!kiosk.prefs.header}
	class:no-clock={!kiosk.prefs.clock}
	class:cursor-on={cursorOn}
	style={accentStyle}
	data-mode={kiosk.mode}
	data-layout={kiosk.effectiveLayout}
>
	<div class="kiosk">
		<header class="kiosk-header">
			<div class="brand">
				{#if kiosk.cinema?.logo_url}
					<img class="brand-logo" src={kiosk.cinema.logo_url} alt={kiosk.cinema.name} />
				{:else}
					<span class="brand-name">{kiosk.cinema?.name ?? 'Cinefin'}</span>
				{/if}
			</div>
			<div class="header-rule" aria-hidden="true"></div>
			<div class="header-clock">
				<span class="clock-time">{kiosk.headerClockText}</span>
				<span class="clock-date">{kiosk.headerDateText}</span>
			</div>
		</header>

		<main class="kiosk-stage" aria-live="off">
			{#if kiosk.booted}
				{#key stageKey}
					<div
						class="stage-scene"
						in:fade={{ duration: MODE_FADE_MS, delay: 150 }}
						out:fade={{ duration: MODE_FADE_MS }}
					>
						{#if kiosk.mode === 'playout'}
							<PlayoutTakeover {kiosk} />
						{:else if kiosk.mode === 'countdown'}
							<CountdownTakeover {kiosk} />
						{:else if kiosk.mode === 'night'}
							<div class="night"><div class="night-clock">{kiosk.headerClockText}</div></div>
						{:else}
							<Layout {kiosk} />
						{/if}
					</div>
				{/key}
			{/if}
		</main>

		{#if kiosk.prefs.clock && !kiosk.prefs.header}
			<div class="floating-clock">{kiosk.headerClockText}</div>
		{/if}
	</div>

	<Picker {kiosk} oncursor={(v) => (cursorOn = v)} />
</div>
