<script lang="ts">
	import type { KioskController } from './controller.svelte';
	import { dayLabel, fmtClock, fmtRuntime, isRunning } from './time';
	import type { KioskScreening } from './types';

	interface Props {
		kiosk: KioskController;
		screening: KioskScreening;
	}
	let { kiosk, screening }: Props = $props();

	const running = $derived(isRunning(screening, kiosk.now));
	const feats = $derived(kiosk.screeningFeatures(screening));
	const feature = $derived(feats[0] ?? null);
	const billTitles = $derived(feats.map((f) => f.title).join(' + '));
	const sub = $derived(
		[
			billTitles && billTitles !== screening.programme ? billTitles : '',
			fmtRuntime(screening.runtime)
		]
			.filter(Boolean)
			.join(' - ')
	);
</script>

<div class="nn-row" class:running>
	<div class="nn-row-time">
		<span class="row-day">
			{#if running}<span class="live-dot"></span>Now{:else}{dayLabel(screening.start)}{/if}
		</span>
		<span class="row-clock">{fmtClock(screening.start)}</span>
	</div>
	<div class="nn-row-info">
		<div class="row-name">{screening.programme}</div>
		{#if sub}<div class="row-sub">{sub}</div>{/if}
	</div>
	{#if feature?.cert}
		<div class="nn-row-cert"><span class="cert">{feature.cert}</span></div>
	{/if}
</div>
