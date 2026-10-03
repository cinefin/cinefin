<script lang="ts">
	import Header from './Header.svelte';
	import Posters from './Posters.svelte';
	import { day } from './format';
	import type { Kiosk } from './kiosk.svelte';

	let { kiosk }: { kiosk: Kiosk } = $props();

	const rows = $derived(
		kiosk.upcoming.filter((s) => Date.parse(s.start) - kiosk.now < 7 * 86_400_000).slice(0, 5)
	);
	const doors = $derived(kiosk.settings?.doors_minutes ?? 0);
</script>

<div class="scene pad">
	<Header {kiosk} />
	<div class="muted heading">This week</div>
	<div class="list">
		{#each rows as s, i (s.id)}
			{@const b = kiosk.bill(s)}
			{@const line = kiosk.line(s, false)}
			{@const d = day(s.start, kiosk.now)}
			{@const cert = b.film?.cert || (b.films.length === 1 ? b.films[0].cert : '')}
			<div class="row" class:first={i === 0}>
				<span class="day" class:soft={i > 0}>
					{#if i === 0 && (d === 'Tonight' || d === 'Today')}<span class="lamp"></span>{/if}{d}
				</span>
				<span class="time" class:soft={i > 0}>{kiosk.time(s.start)}</span>
				<Posters films={b.film ? [b.film] : b.films} width={b.films.length > 1 ? 100 : 64} />
				<span class="what">
					<span class="name">{b.title}</span>
					<span class="muted sub"
						>{line.names}{#if line.mono}<span class="mono"
								>{line.names ? ' · ' : ''}{line.mono}</span
							>{/if}</span
					>
				</span>
				<span class="mono cert"
					>{#if cert}<span>{cert}</span>{/if}</span
				>
			</div>
		{/each}
	</div>
	{#if doors}
		<div class="faint foot">
			Doors open {doors === 30 ? 'half an hour' : `${doors} minutes`} before each screening.
		</div>
	{/if}
</div>

<style>
	.heading {
		margin-top: 60px;
		font-size: 24px;
	}
	.list {
		margin-top: 16px;
		background: var(--color-surface-1);
		border: 1px solid var(--color-border);
	}
	.row {
		display: grid;
		grid-template-columns: 220px 200px 130px minmax(0, 1fr) 100px;
		align-items: center;
		gap: 0 32px;
		padding: 22px 36px;
		border-top: 1px solid var(--color-border);
	}
	.row.first {
		border-top: 0;
		background: var(--color-surface-2);
	}
	.day {
		display: flex;
		align-items: center;
		gap: 12px;
		font-size: 26px;
	}
	.time {
		font-size: 60px;
		line-height: 1;
	}
	.what {
		min-width: 0;
	}
	.what .name {
		display: block;
		font-size: 46px;
		line-height: 1.05;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.sub {
		display: block;
		margin-top: 8px;
		font-size: 22px;
	}
	.cert {
		text-align: center;
		font-size: 24px;
		font-weight: 500;
	}
	.cert span {
		display: block;
		padding: 4px 0;
		border: 1px solid var(--color-border-strong);
	}
	.foot {
		margin-top: auto;
		font-size: 22px;
	}
</style>
