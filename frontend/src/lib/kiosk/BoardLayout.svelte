<script lang="ts">
	import KioskEmpty from './KioskEmpty.svelte';
	import type { KioskController } from './controller.svelte';
	import { countdownText, dayLabel, fmtClock, isRunning } from './time';

	interface Props {
		kiosk: KioskController;
	}
	let { kiosk }: Props = $props();

	const screenings = $derived(kiosk.activeScreenings.slice(0, 10));
</script>

{#if !screenings.length}
	<KioskEmpty
		title="No showings scheduled"
		sub="The schedule board fills as screenings are booked"
	/>
{:else}
	<div class="board">
		<div class="bd-head">
			<span class="bd-day">Day</span>
			<span class="bd-time">Time</span>
			<span class="bd-name">Programme</span>
			<span class="bd-cert"></span>
			<span class="bd-status">Status</span>
		</div>
		{#each screenings as s (s.id)}
			{@const running = isRunning(s, kiosk.now)}
			{@const feats = kiosk.screeningFeatures(s)}
			{@const bill = feats.map((f) => f.title).join(' + ')}
			<div class="bd-row" class:running>
				<span class="bd-day">
					{#if running}<span class="live-dot"></span>Now{:else}{dayLabel(s.start)}{/if}
				</span>
				<span class="bd-time">{fmtClock(s.start)}</span>
				<span class="bd-name">
					{s.programme}{#if bill && bill !== s.programme}<em class="bd-bill">{bill}</em>{/if}
				</span>
				<span class="bd-cert">
					{#if feats[0]?.cert}<span class="cert">{feats[0].cert}</span>{/if}
				</span>
				<span class="bd-status">{countdownText(s, kiosk.now)}</span>
			</div>
		{/each}
	</div>
{/if}
