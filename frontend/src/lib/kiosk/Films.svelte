<script lang="ts">
	import { fade } from 'svelte/transition';
	import Backdrop from './Backdrop.svelte';
	import Header from './Header.svelte';
	import Poster from './Poster.svelte';
	import { day, dayIn, facts, fit } from './format';
	import type { Kiosk } from './kiosk.svelte';

	let { kiosk }: { kiosk: Kiosk } = $props();

	const film = $derived(kiosk.pick(kiosk.turnFilms)!);
	const showing = $derived(kiosk.showingOf(film));
	const about = $derived(
		[
			film.genres
				.join(', ')
				.toLowerCase()
				.replace(/^./, (c) => c.toUpperCase()),
			film.director && `directed by ${film.director}`
		]
			.filter(Boolean)
			.join(' · ')
	);
	const band = $derived(kiosk.upcoming.slice(0, 2));
</script>

{#key film.id}
	<div class="scene" in:fade={{ duration: 600, delay: 200 }} out:fade={{ duration: 600 }}>
		<Backdrop {film} side="left" />
		<div class="body">
			<Header {kiosk} />
			<div class="main">
				<Poster {film} grain style="width: 460px" />
				<div>
					<div class="name title" style="font-size: {fit(film.title, 120)}px">{film.title}</div>
					<div class="mono muted facts">{facts(film)}</div>
					{#if about}<div class="soft about">{about}</div>{/if}
					{#if film.synopsis}<p class="synopsis">{film.synopsis}</p>{/if}
					{#if showing}
						<div class="soft showing">
							Showing {dayIn(showing.start, kiosk.now)} at
							<span class="mono">{kiosk.time(showing.start)}</span>
						</div>
					{/if}
				</div>
			</div>
		</div>
		{#if band.length}
			<div class="band">
				{#each band as s, i (s.id)}
					{@const d = day(s.start, kiosk.now)}
					{#if i === 0}
						{#if d === 'Tonight' || d === 'Today'}<span class="lamp"></span>{/if}
						<span class="muted">{d}</span>
					{:else}
						<span class="muted then"
							>then{d === day(band[0].start, kiosk.now)
								? ''
								: ` ${dayIn(s.start, kiosk.now)}`}</span
						>
					{/if}
					<span class="time">{kiosk.time(s.start)}</span>
					<span class="name">{kiosk.bill(s).title}</span>
				{/each}
			</div>
		{/if}
	</div>
{/key}

<style>
	.body {
		position: relative;
		flex: 1;
		min-height: 0;
		box-sizing: border-box;
		padding: 64px 80px 0;
		display: flex;
		flex-direction: column;
	}
	.main {
		display: grid;
		grid-template-columns: 460px minmax(0, 1fr);
		gap: 80px;
		margin: auto 0;
		align-items: center;
	}
	.title {
		font-size: 120px;
		line-height: 0.95;
	}
	.facts {
		margin-top: 24px;
		font-size: 28px;
	}
	.about {
		margin-top: 14px;
		font-size: 26px;
	}
	.synopsis {
		margin-top: 34px;
		font-size: 28px;
	}
	.showing {
		margin-top: 40px;
		font-size: 26px;
	}
	.band {
		position: relative;
		height: 120px;
		flex: none;
		display: flex;
		align-items: center;
		gap: 18px;
		padding: 0 80px;
		background: var(--color-surface-1);
		border-top: 1px solid var(--color-border);
		font-size: 30px;
		white-space: nowrap;
		overflow: hidden;
	}
	.band .time {
		line-height: 1;
	}
	.then {
		margin-left: 32px;
	}
</style>
