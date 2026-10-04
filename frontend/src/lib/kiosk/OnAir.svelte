<script lang="ts">
	import { screeningTitle } from '$lib/playout/screening-title';
	import type { PlayoutStatus } from '$lib/playout/phase';
	import Backdrop from './Backdrop.svelte';
	import Header from './Header.svelte';
	import Posters from './Posters.svelte';
	import { dayIn, facts, fit } from './format';
	import type { Kiosk, KioskFilm } from './kiosk.svelte';

	let { kiosk, status }: { kiosk: Kiosk; status: PlayoutStatus } = $props();

	const name = $derived(status.programme?.name ?? '');
	const films = $derived(
		(status.programme?.features ?? []).map(
			(f): Partial<KioskFilm> =>
				kiosk.film(f.id) ?? {
					id: f.id,
					title: f.title,
					year: f.year,
					cert: f.certification ?? '',
					runtime: f.runtime_minutes ?? 0,
					poster: f.thumbnail_url
				}
		)
	);
	const bill = $derived(screeningTitle(name, films as (Partial<KioskFilm> & { title: string })[]));
	const screening = $derived(
		kiosk.upcoming.find((s) => s.status === 'running' && s.programme_id === status.programme?.id)
	);
	// Before the programme's first item: the title card, playing or paused.
	const preshow = $derived(status.playlist?.current_position == null);
	const paused = $derived(status.phase === 'paused' && !preshow);
	// The screening's own times, else worked out from how far the programme has run.
	const times = $derived.by(() => {
		if (screening) return { started: Date.parse(screening.start), ends: Date.parse(screening.end) };
		const p = status.playlist;
		if (!p || preshow) return null;
		const started = Date.now() - p.programme_elapsed_time * 1000;
		return { started, ends: started + p.programme_total_duration * 1000 };
	});
	const next = $derived(
		kiosk.upcoming.find((s) => s.id !== screening?.id && Date.parse(s.start) > kiosk.now)
	);
	const doors = $derived(kiosk.settings?.doors_minutes ?? 0);
</script>

<div class="scene">
	<Backdrop film={bill.film ?? bill.films[0]} />
	<div class="body">
		<Header {kiosk} quiet />
		<div class="main">
			<div>
				<div class="muted label">
					{preshow ? 'Starting soon' : paused ? 'Paused' : 'Now showing'}
				</div>
				<div class="name title" style="font-size: {fit(bill.title, 150)}px">{bill.title}</div>
				{#if bill.film}
					<div class="mono muted facts">{facts(bill.film)}</div>
				{:else}
					{#each bill.films as film (film.id)}
						<div class="film">{film.title} <span class="mono muted">{facts(film)}</span></div>
					{/each}
				{/if}
				{#if paused}
					<div class="soft when">Back shortly</div>
				{:else if times}
					<div class="soft when">
						{preshow ? 'Starting at' : 'Started at'}
						<span class="mono">{kiosk.time(times.started)}</span>
						· ends about
						<span class="mono">{kiosk.time(times.ends)}</span>
					</div>
				{/if}
				{#if next}
					<div class="muted next">
						Next: {kiosk.bill(next).title}, {dayIn(next.start, kiosk.now)} at
						<span class="mono">{kiosk.time(next.start)}</span>{#if doors}
							· doors <span class="mono">{kiosk.time(Date.parse(next.start) - doors * 60_000)}</span
							>{/if}
					</div>
				{/if}
			</div>
			<Posters films={bill.film ? [bill.film] : bill.films} width={460} />
		</div>
	</div>
</div>

<style>
	.body {
		position: relative;
		height: 100%;
		box-sizing: border-box;
		padding: 64px 80px;
		display: flex;
		flex-direction: column;
	}
	.main {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 460px;
		gap: 90px;
		margin-top: auto;
		align-items: end;
	}
	.label {
		font-size: 30px;
	}
	.title {
		margin-top: 24px;
		font-size: 150px;
		line-height: 0.92;
	}
	.facts {
		margin-top: 22px;
		font-size: 26px;
	}
	.film {
		margin-top: 14px;
		font-size: 32px;
	}
	.film .mono {
		font-size: 26px;
	}
	.when {
		margin-top: 70px;
		font-size: 32px;
	}
	.next {
		margin-top: 24px;
		font-size: 26px;
	}
</style>
