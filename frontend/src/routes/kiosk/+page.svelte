<script lang="ts">
	// Kiosk display — public wall display; runs 24/7 unattended (silent fetch failures,
	// timers tear down with the component, self-reloads on a reload_key change).
	import { fade } from 'svelte/transition';
	import { KioskController } from '$lib/kiosk/controller.svelte';
	import BoardLayout from '$lib/kiosk/BoardLayout.svelte';
	import CountdownTakeover from '$lib/kiosk/CountdownTakeover.svelte';
	import NightMode from '$lib/kiosk/NightMode.svelte';
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

	// One key for "what the stage shows": a change crossfades the scene.
	const stageKey = $derived.by((): string => {
		switch (kiosk.mode) {
			case 'playout':
				return `playout:${kiosk.playoutKey}`;
			case 'countdown':
				return `countdown:${kiosk.countdownTarget?.id ?? 0}`;
			case 'night':
				return 'night';
			default:
				return `layout:${kiosk.effectiveLayout}`;
		}
	});

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
							<NightMode {kiosk} />
						{:else if kiosk.effectiveLayout === 'spotlight'}
							<SpotlightLayout {kiosk} />
						{:else if kiosk.effectiveLayout === 'split'}
							<SplitLayout {kiosk} />
						{:else if kiosk.effectiveLayout === 'board'}
							<BoardLayout {kiosk} />
						{:else if kiosk.effectiveLayout === 'tonight'}
							<TonightLayout {kiosk} />
						{:else}
							<WallLayout {kiosk} />
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
