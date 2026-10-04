<script lang="ts">
	import { fade } from 'svelte/transition';
	import Doors from '$lib/kiosk/Doors.svelte';
	import Films from '$lib/kiosk/Films.svelte';
	import { Kiosk } from '$lib/kiosk/kiosk.svelte';
	import OnAir from '$lib/kiosk/OnAir.svelte';
	import PosterWall from '$lib/kiosk/PosterWall.svelte';
	import Quiet from '$lib/kiosk/Quiet.svelte';
	import Screenings from '$lib/kiosk/Screenings.svelte';
	import Week from '$lib/kiosk/Week.svelte';
	import WhatsOn from '$lib/kiosk/WhatsOn.svelte';
	import '$lib/kiosk/kiosk.css';

	const kiosk = new Kiosk();
	$effect(() => kiosk.start());

	const posters = new URLSearchParams(location.search).get('mode') === 'posters';

	let w = $state(1920);
	let h = $state(1080);
	const scale = $derived(Math.min(w / 1920, h / 1080));

	// Each option needs something to show; with nothing booked it falls back to the films.
	const view = $derived.by(() => {
		const booked = kiosk.upcoming.length > 0;
		const films = kiosk.turnFilms.length > 0;
		if (kiosk.between === 'films') return films ? 'films' : booked ? 'whats_on' : 'quiet';
		return booked ? kiosk.between : films ? 'films' : 'quiet';
	});
	const key = $derived(
		kiosk.screen === 'between'
			? view
			: kiosk.screen === 'doors'
				? `doors:${kiosk.doors?.id}`
				: kiosk.screen === 'on_air'
					? `on_air:${kiosk.onAir?.programme?.id}`
					: 'night'
	);
</script>

<svelte:head>
	<title>{kiosk.cinema?.name ?? 'Cinefin'}</title>
</svelte:head>

<div class="kiosk" bind:clientWidth={w} bind:clientHeight={h}>
	{#if posters}
		<PosterWall {kiosk} />
	{:else if kiosk.data}
		<div class="stage" style="transform: translate(-50%, -50%) scale({scale})">
			{#key key}
				<div class="fill" in:fade={{ duration: 600, delay: 200 }} out:fade={{ duration: 600 }}>
					{#if kiosk.screen === 'on_air' && kiosk.onAir}
						<OnAir {kiosk} status={kiosk.onAir} />
					{:else if kiosk.screen === 'doors' && kiosk.doors}
						<Doors {kiosk} screening={kiosk.doors} />
					{:else if kiosk.screen === 'night'}
						<Quiet {kiosk} dim />
					{:else if view === 'whats_on'}
						<WhatsOn {kiosk} />
					{:else if view === 'screenings'}
						<Screenings {kiosk} />
					{:else if view === 'films'}
						<Films {kiosk} />
					{:else if view === 'week'}
						<Week {kiosk} />
					{:else}
						<Quiet {kiosk} />
					{/if}
				</div>
			{/key}
		</div>
	{/if}
</div>

<style>
	.kiosk {
		z-index: 50;
	}
	.stage {
		position: absolute;
		left: 50%;
		top: 50%;
		width: 1920px;
		height: 1080px;
		overflow: hidden;
	}
	.fill {
		position: absolute;
		inset: 0;
	}
</style>
