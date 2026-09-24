<script lang="ts">
	import Backdrop from './Backdrop.svelte';
	import MetaRow from './MetaRow.svelte';
	import Posters from './Posters.svelte';
	import type { KioskController } from './controller.svelte';
	import { fmtClock } from './time';

	interface Props {
		kiosk: KioskController;
	}
	let { kiosk }: Props = $props();

	const screening = $derived(kiosk.countdownTarget);
	const feats = $derived(screening ? kiosk.screeningFeatures(screening) : []);
	const single = $derived(feats.length === 1 ? feats[0] : null);
	const title = $derived(single ? single.title : (screening?.programme ?? ''));
	const billTitles = $derived(feats.map((f) => f.title).join('  +  '));
	const subLine = $derived(
		single
			? single.title !== screening?.programme
				? (screening?.programme ?? '')
				: ''
			: feats.length > 1
				? billTitles
				: ''
	);
	const clockText = $derived(screening ? kiosk.countdownClock(screening) : '');
</script>

{#if screening}
	<div class="countdown">
		<Backdrop film={feats[0] ?? null} />
		<div class="countdown-inner">
			<Posters films={feats.length ? feats : [{ title }]} cls="countdown-poster" />
			<div class="countdown-body">
				<div class="eyebrow">Next Showing</div>
				<h1 class="countdown-title">{title}</h1>
				{#if subLine}<div class="nn-programme">{subLine}</div>{/if}
				{#if single}<MetaRow film={single} />{/if}
				<div class="countdown-timer">
					{#if clockText !== 'Starting now'}
						<span class="count-label">Starts in</span>
					{/if}
					<span class="count-clock" class:starting={clockText === 'Starting now'}>
						{clockText}
					</span>
				</div>
				<div class="count-at">
					<span class="nn-clockplate">{fmtClock(screening.start)}</span>
				</div>
			</div>
		</div>
	</div>
{/if}
