<script lang="ts">
	import Backdrop from './Backdrop.svelte';
	import MetaRow from './MetaRow.svelte';
	import Posters from './Posters.svelte';
	import type { KioskController } from './controller.svelte';

	interface Props {
		kiosk: KioskController;
	}
	let { kiosk }: Props = $props();

	const p = $derived(kiosk.playout);
	const films = $derived(p ? kiosk.takeoverFilms(p) : []);
	const single = $derived(films.length === 1 ? films[0] : null);
	const titles = $derived(
		films
			.map((f) => f.title)
			.filter(Boolean)
			.join('  +  ')
	);
	const showBill = $derived(!!titles && !(single && single.title === p?.programmeName));
	const showBar = $derived(!!p && p.programmeDuration > 0);
	const progress = $derived(
		p && p.programmeDuration > 0 ? kiosk.programmeElapsedNow(p) / p.programmeDuration : 0
	);
</script>

{#if p}
	<div class="takeover">
		<Backdrop film={films[0] ?? null} />
		<div class="takeover-inner">
			{#if films.length}
				<Posters {films} cls="takeover-poster" />
			{/if}
			<div class="takeover-body">
				<div class="eyebrow">
					{#if p.programmeState === 'pre_show'}
						<span class="live-dot"></span>Pre-show
					{:else if p.paused}
						Paused
					{:else}
						<span class="live-dot"></span>Now Showing
					{/if}
				</div>
				<h1 class="takeover-title">{p.programmeName}</h1>
				{#if showBill}<div class="nn-programme">{titles}</div>{/if}
				{#if single}<MetaRow film={single} />{/if}
				<div class="takeover-progress">
					{#if showBar}
						<span class="bar"><i style="transform:scaleX({progress.toFixed(4)})"></i></span>
					{/if}
					<em>{kiosk.playoutEndsText(p)}</em>
				</div>
			</div>
		</div>
	</div>
{/if}
