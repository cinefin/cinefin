<script lang="ts">
	import { fade } from 'svelte/transition';
	import Backdrop from './Backdrop.svelte';
	import Header from './Header.svelte';
	import Posters from './Posters.svelte';
	import { day, facts, fit } from './format';
	import type { Kiosk } from './kiosk.svelte';

	let { kiosk }: { kiosk: Kiosk } = $props();

	const s = $derived(kiosk.pick(kiosk.upcoming)!);
	const bill = $derived(kiosk.bill(s));
	const films = $derived(bill.film ? [bill.film] : bill.films);
	const synopsis = $derived(films.length === 1 ? films[0].synopsis : '');
	const others = $derived(kiosk.upcoming.filter((o) => o.id !== s.id).slice(0, 3));
</script>

{#key s.id}
	<div class="scene" in:fade={{ duration: 600, delay: 200 }} out:fade={{ duration: 600 }}>
		<Backdrop film={films[0]} />
		<div class="body">
			<Header {kiosk} />
			<div class="main">
				<Posters {films} width={420} />
				<div>
					<div class="soft when">
						{day(s.start, kiosk.now)} <span class="time">{kiosk.time(s.start)}</span>
					</div>
					<div class="name title" style="font-size: {fit(bill.title, 112)}px">{bill.title}</div>
					{#if bill.film}
						<div class="mono muted facts">{facts(bill.film)}</div>
					{:else}
						<div class="films">
							{#each bill.films as film (film.id)}
								<span>{film.title} <span class="mono muted">{facts(film)}</span></span>
							{/each}
						</div>
					{/if}
					{#if synopsis}<p class="synopsis">{synopsis}</p>{/if}
				</div>
			</div>
			{#if others.length}
				<div class="others faint">
					{#each others as o (o.id)}
						<span
							>{day(o.start, kiosk.now)}
							<span class="mono muted">{kiosk.time(o.start)}</span>
							<span class="soft">{kiosk.bill(o).title}</span></span
						>
					{/each}
				</div>
			{/if}
		</div>
	</div>
{/key}

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
		grid-template-columns: 420px minmax(0, 1fr);
		gap: 72px;
		margin-top: 60px;
		align-items: center;
	}
	.when {
		font-size: 36px;
		line-height: 1;
	}
	.title {
		margin-top: 24px;
		font-size: 112px;
		line-height: 0.95;
	}
	.facts {
		margin-top: 22px;
		font-size: 28px;
	}
	.films {
		margin-top: 34px;
		display: flex;
		flex-direction: column;
		gap: 14px;
		font-size: 32px;
	}
	.films .mono {
		font-size: 26px;
	}
	.synopsis {
		margin-top: 30px;
	}
	.others {
		margin-top: auto;
		display: flex;
		gap: 48px;
		font-size: 24px;
	}
</style>
