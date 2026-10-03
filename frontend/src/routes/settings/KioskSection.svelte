<script lang="ts">
	import { ExternalLink } from '@lucide/svelte';
	import { base } from '$app/paths';
	import type { SettingsStore } from '$lib/settings/form.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import StoreField, { storeField } from '$lib/settings/StoreField.svelte';
	import StoreToggle from '$lib/settings/StoreToggle.svelte';
	import SectionTabs from './SectionTabs.svelte';
	import TabPanel from './TabPanel.svelte';

	let { store }: { store: SettingsStore } = $props();

	const TABS = [
		{ id: 'layout', label: 'Layout' },
		{ id: 'chrome', label: 'Chrome' },
		{ id: 'takeovers', label: 'Takeovers' }
	];
	let tab = $state('layout');
	const timeCls =
		'h-9 w-full rounded-md border border-border-strong bg-surface-2 px-3 text-sm text-text focus:border-accent-dim';

	const LAYOUT = [
		storeField('kiosk_layout', 'Layout', 'set-kiosk-layout', {
			options: [
				['wall', 'Poster wall'],
				['spotlight', 'Spotlight'],
				['split', 'Split (spotlight + showings)'],
				['board', 'Schedule board'],
				['tonight', 'Tonight (next showing only)'],
				['auto', 'Auto (picks by schedule)']
			]
		}),
		storeField('kiosk_rotate_minutes', 'Rotate layouts', 'set-kiosk-rotate', {
			hint: 'Cycles the ambient layouts (wall, spotlight, split). Ignored while the layout is Auto.',
			options: [
				['0', 'Off'],
				...[2, 5, 10, 15, 30].map((n) => [String(n), `Every ${n} minutes`] as const),
				['60', 'Every hour']
			]
		}),
		storeField('kiosk_content_source', 'Movies shown', 'set-kiosk-source', {
			hint: "Flag movies from the library's kiosk toggle.",
			options: [
				['flagged', 'Movies flagged for the kiosk'],
				['all', 'The whole library'],
				['scheduled', 'Only movies with upcoming showings']
			]
		})
	];
	const NIGHT = [
		storeField('kiosk_night_start', 'Quiet from', 'set-kiosk-night-start'),
		storeField('kiosk_night_end', 'Until', 'set-kiosk-night-end')
	];
</script>

<div class="mb-4 flex flex-wrap items-center gap-3">
	<Button href="{base}/kiosk" title="Open the kiosk display">
		<ExternalLink size={14} /> Open kiosk
	</Button>
	<p class="text-xs text-faint">
		A live kiosk picks saved changes up within a few minutes on its own refresh.
	</p>
</div>

<SectionTabs tabs={TABS} bind:value={tab} label="Kiosk settings" prefix="kt" />

{#if tab === 'layout'}
	<TabPanel prefix="kt" tab="layout" class="mt-4 grid gap-4 sm:grid-cols-2">
		{#each LAYOUT as f (f.id)}
			<StoreField {store} {...f} input="w-full" />
		{/each}
	</TabPanel>
{:else if tab === 'chrome'}
	<TabPanel prefix="kt" tab="chrome" class="mt-4 max-w-xl space-y-2.5">
		<StoreToggle {store} field="kiosk_header" label="Theater name / logo header" />
		<StoreToggle {store} field="kiosk_clock" label="Clock" />
		<StoreToggle {store} field="kiosk_show_showtimes" label="Showtimes on poster-wall tiles" />
	</TabPanel>
{:else if tab === 'takeovers'}
	<TabPanel prefix="kt" tab="takeovers" class="mt-4 max-w-xl space-y-4">
		<StoreToggle
			{store}
			field="kiosk_takeover"
			label="Now Showing takeover"
			hint="While a programme is live the kiosk switches to a full-screen Now Showing card - the programme's name and artwork - then returns to its layout when the show ends."
		/>
		<StoreField
			{store}
			field="kiosk_countdown_minutes"
			label="Countdown threshold (min)"
			id="set-kiosk-countdown"
			hint="Full-screen countdown when the next showing is this close. 0 turns it off."
			type="number"
			input="max-w-32"
		/>

		<div class="mt-6 border-t border-border pt-5">
			<h3 class="mb-3 text-[0.78125rem] font-medium text-muted">Night hours</h3>
			<div class="space-y-4">
				<StoreToggle {store} field="kiosk_night" label="Dim to a clock overnight" />
				<div class="grid max-w-md gap-4 sm:grid-cols-2">
					{#each NIGHT as f (f.id)}
						<StoreField {store} {...f} type="time" input={timeCls} />
					{/each}
				</div>
				<p class="text-xs text-faint">
					A live programme or an imminent showing wakes the display regardless.
				</p>
			</div>
		</div>
	</TabPanel>
{/if}
