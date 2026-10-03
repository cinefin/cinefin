<script lang="ts">
	import Backdrop from './Backdrop.svelte';
	import MetaRow from './MetaRow.svelte';
	import Posters from './Posters.svelte';
	import type { KioskController } from './controller.svelte';
	import { fmtClock } from './time';

	let { kiosk }: { kiosk: KioskController } = $props();

	const screening = $derived(kiosk.countdownTarget);
	const { feats, single, title, sub: subLine } = $derived(kiosk.bill(screening));
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
