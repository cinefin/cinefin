<script lang="ts">
	import Header from './Header.svelte';
	import Posters from './Posters.svelte';
	import { day, facts, fit } from './format';
	import type { Kiosk } from './kiosk.svelte';

	let { kiosk }: { kiosk: Kiosk } = $props();

	const next = $derived(kiosk.upcoming[0]);
	const bill = $derived(kiosk.bill(next));
	const today = $derived(day(next.start, kiosk.now));
	const doorsAt = $derived.by(() => {
		const lead = kiosk.settings?.doors_minutes ?? 0;
		return lead ? kiosk.time(Date.parse(next.start) - lead * 60_000) : '';
	});
	const synopsis = $derived(
		bill.film?.synopsis || (bill.films.length === 1 ? bill.films[0].synopsis : '')
	);
	const later = $derived(kiosk.upcoming.slice(1, 4));
</script>

<div class="scene pad">
	<Header {kiosk} />
	<section class="hero">
		<Posters films={bill.film ? [bill.film] : bill.films} width={380} />
		<div>
			<div class="label muted">
				{#if today === 'Tonight' || today === 'Today'}<span class="lamp"></span>{/if}
				{today}{doorsAt ? ` · doors open at ${doorsAt}` : ''}
			</div>
			<div class="time start">{kiosk.time(next.start)}</div>
			<div class="name title" style="font-size: {fit(bill.title, 104)}px">{bill.title}</div>
			{#if bill.film}
				<div class="mono muted facts">{facts(bill.film)}</div>
			{:else}
				{#each bill.films as film (film.id)}
					<div class="film">{film.title} <span class="mono muted">{facts(film)}</span></div>
				{/each}
			{/if}
			{#if synopsis}<p class="synopsis">{synopsis}</p>{/if}
		</div>
	</section>

	{#if later.length}
		<section class="later">
			<div class="faint">Coming up</div>
			<div class="cards">
				{#each later as s (s.id)}
					{@const b = kiosk.bill(s)}
					{@const line = kiosk.line(s)}
					<div class="card">
						<Posters films={b.film ? [b.film] : b.films} width={b.films.length > 1 ? 110 : 72} />
						<div>
							<div class="mono muted when">{kiosk.when(s)}</div>
							<div class="name">{b.title}</div>
							<div class="muted sub">
								{line.names}{#if line.mono}<span class="mono"
										>{line.names ? ' · ' : ''}{line.mono}</span
									>{/if}
							</div>
						</div>
					</div>
				{/each}
			</div>
		</section>
	{/if}
</div>

<style>
	.hero {
		display: grid;
		grid-template-columns: 380px minmax(0, 1fr);
		gap: 64px;
		margin-top: 64px;
		align-items: end;
	}
	.label {
		display: flex;
		align-items: center;
		gap: 12px;
		font-size: 26px;
	}
	.start {
		margin-top: 26px;
		font-size: 160px;
	}
	.title {
		margin-top: 28px;
		font-size: 104px;
	}
	.facts {
		margin-top: 20px;
		font-size: 28px;
	}
	.film {
		margin-top: 14px;
		font-size: 32px;
	}
	.film .mono {
		font-size: 26px;
	}
	.synopsis {
		margin-top: 22px;
	}
	.later {
		margin-top: auto;
		padding-top: 40px;
		font-size: 22px;
	}
	.cards {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 24px;
		margin-top: 14px;
	}
	.card {
		display: flex;
		gap: 22px;
		align-items: center;
		padding: 18px;
		background: var(--color-surface-1);
		border: 1px solid var(--color-border);
		min-width: 0;
	}
	.card .name {
		margin-top: 6px;
		font-size: 32px;
		line-height: 1.05;
	}
	.sub {
		margin-top: 6px;
		font-size: 20px;
	}
</style>
