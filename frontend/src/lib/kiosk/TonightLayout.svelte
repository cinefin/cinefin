<script lang="ts">
	import Backdrop from './Backdrop.svelte';
	import KioskEmpty from './KioskEmpty.svelte';
	import MetaRow from './MetaRow.svelte';
	import Posters from './Posters.svelte';
	import type { KioskController } from './controller.svelte';
	import { countdownText, dayLabel, fmtClock, isRunning } from './time';

	interface Props {
		kiosk: KioskController;
	}
	let { kiosk }: Props = $props();

	const next = $derived(kiosk.activeScreenings[0] ?? null);
	const running = $derived(next ? isRunning(next, kiosk.now) : false);
	const feats = $derived(next ? kiosk.screeningFeatures(next) : []);
	const single = $derived(feats.length === 1 ? feats[0] : null);
	const title = $derived(single ? single.title : (next?.programme ?? ''));
	const billTitles = $derived(feats.map((f) => f.title).join('  +  '));
	const subLine = $derived(
		single
			? single.title !== next?.programme
				? (next?.programme ?? '')
				: ''
			: feats.length > 1
				? billTitles
				: ''
	);
</script>

{#if !next}
	<KioskEmpty title="No showings scheduled" sub="Check back soon for the next screening" />
{:else}
	<div class="tonight">
		<Backdrop film={feats[0] ?? null} />
		<div class="tn-inner">
			<Posters films={feats.length ? feats : [{ title }]} cls="tn-poster" />
			<div class="tn-body">
				<div class="eyebrow">
					{#if running}
						<span class="live-dot"></span>Now Showing
					{:else}
						{dayLabel(next.start) === 'Today' ? 'Tonight' : 'Next Showing'}
					{/if}
				</div>
				<h1 class="tn-title">{title}</h1>
				{#if subLine}<div class="nn-programme">{subLine}</div>{/if}
				{#if single}<MetaRow film={single} />{/if}
				<div class="tn-time">
					<span class="nn-clockplate">{fmtClock(next.start)}</span>
					<span class="nn-count">{countdownText(next, kiosk.now)}</span>
				</div>
			</div>
		</div>
	</div>
{/if}
