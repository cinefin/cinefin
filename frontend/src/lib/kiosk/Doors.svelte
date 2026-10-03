<script lang="ts">
	import Backdrop from './Backdrop.svelte';
	import Header from './Header.svelte';
	import Posters from './Posters.svelte';
	import { dayIn, facts, fit } from './format';
	import type { Kiosk, KioskScreening } from './kiosk.svelte';

	let { kiosk, screening: s }: { kiosk: Kiosk; screening: KioskScreening } = $props();

	const bill = $derived(kiosk.bill(s));
	const films = $derived(bill.film ? [bill.film] : bill.films);
	const then = $derived(kiosk.upcoming.find((o) => Date.parse(o.start) > Date.parse(s.start)));
</script>

<div class="scene">
	<Backdrop film={films[0]} side="left" />
	<div class="body">
		<Header {kiosk} quiet />
		<div class="main">
			<Posters {films} width={500} />
			<div>
				<div class="label"><span class="lamp"></span>Doors open</div>
				<div class="name title" style="font-size: {fit(bill.title, 120)}px">{bill.title}</div>
				{#if bill.film}
					<div class="mono muted facts">{facts(bill.film)}</div>
				{:else}
					{#each bill.films as film (film.id)}
						<div class="film">{film.title} <span class="mono muted">{facts(film)}</span></div>
					{/each}
				{/if}
				<div class="muted starts">Starts at</div>
				<div class="time start">{kiosk.time(s.start)}</div>
				{#if then}
					<div class="muted then">
						Then {kiosk.bill(then).title}, {dayIn(then.start, kiosk.now)} at
						<span class="mono">{kiosk.time(then.start)}</span>
					</div>
				{/if}
			</div>
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
		grid-template-columns: 500px minmax(0, 1fr);
		gap: 90px;
		margin: auto 0;
		align-items: center;
	}
	.label {
		display: flex;
		align-items: center;
		gap: 14px;
		font-size: 30px;
	}
	.label .lamp {
		width: 14px;
		height: 14px;
	}
	.title {
		margin-top: 30px;
		font-size: 120px;
		line-height: 0.95;
	}
	.facts {
		margin-top: 22px;
		font-size: 28px;
	}
	.film {
		margin-top: 14px;
		font-size: 32px;
	}
	.film .mono {
		font-size: 26px;
	}
	.starts {
		margin-top: 80px;
		font-size: 30px;
	}
	.start {
		margin-top: 10px;
		font-size: 200px;
	}
	.then {
		margin-top: 50px;
		font-size: 26px;
	}
</style>
