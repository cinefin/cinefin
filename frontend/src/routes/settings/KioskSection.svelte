<script lang="ts">
	import { ExternalLink } from '@lucide/svelte';
	import { base } from '$app/paths';
	import type { SettingsStore } from '$lib/settings/form.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import StoreField, { optionLabel, storeField } from '$lib/settings/StoreField.svelte';
	import StoreSwitch from '$lib/settings/StoreSwitch.svelte';
	import SettingList from './SettingList.svelte';
	import SettingLists from './SettingLists.svelte';
	import SettingRow from './SettingRow.svelte';
	import StoreToggle from '$lib/settings/StoreToggle.svelte';

	let { store }: { store: SettingsStore } = $props();

	const timeCls =
		'h-9 w-full rounded-md border border-border-strong bg-surface-2 px-3 text-sm text-text focus:border-accent-dim';

	const LAYOUT = storeField('kiosk_layout', 'Layout', 'set-kiosk-layout', {
		options: [
			['wall', 'Poster wall'],
			['spotlight', 'Spotlight'],
			['split', 'Split (spotlight + showings)'],
			['board', 'Schedule board'],
			['tonight', 'Tonight (next showing only)'],
			['auto', 'Auto (picks by schedule)']
		]
	});
	const ROTATE = storeField('kiosk_rotate_minutes', 'Rotate layouts', 'set-kiosk-rotate', {
		hint: 'Cycles the ambient layouts (wall, spotlight, split). Ignored while the layout is Auto.',
		options: [
			['0', 'Off'],
			...[2, 5, 10, 15, 30].map((n) => [String(n), `Every ${n} minutes`] as const),
			['60', 'Every hour']
		]
	});
	const SOURCE = storeField('kiosk_content_source', 'Movies shown', 'set-kiosk-source', {
		hint: "Flag movies from the library's kiosk toggle.",
		options: [
			['flagged', 'Movies flagged for the kiosk'],
			['all', 'The whole library'],
			['scheduled', 'Only movies with upcoming showings']
		]
	});

	const shown = (on: boolean) => (on ? 'Shown' : 'Hidden');
	const layoutSummary = $derived.by(() => {
		const m = store.main;
		const rotates = m.kiosk_layout !== 'auto' && m.kiosk_rotate_minutes !== '0';
		const rotate = rotates
			? ` · rotates ${optionLabel(ROTATE, m.kiosk_rotate_minutes).toLowerCase()}`
			: '';
		return optionLabel(LAYOUT, m.kiosk_layout) + rotate;
	});
	const countdownSummary = $derived(
		Number(store.main.kiosk_countdown_minutes) > 0
			? `From ${store.main.kiosk_countdown_minutes} minutes before`
			: 'Off'
	);
	const NIGHT = [
		storeField('kiosk_night_start', 'Quiet from', 'set-kiosk-night-start'),
		storeField('kiosk_night_end', 'Until', 'set-kiosk-night-end')
	];
</script>

<SettingLists>
	<SettingList
		title="The wall screen"
		text="Between screenings · a live kiosk picks changes up within a few minutes"
	>
		{#snippet actions()}
			<Button size="sm" href="{base}/kiosk" title="Open the kiosk display">
				<ExternalLink size={13} /> Open the kiosk
			</Button>
		{/snippet}
		<SettingRow label="Layout" summary={layoutSummary}>
			<div class="grid max-w-xl gap-4 sm:grid-cols-2">
				<StoreField {store} {...LAYOUT} input="w-full" />
				<StoreField {store} {...ROTATE} input="w-full" />
			</div>
		</SettingRow>
		<SettingRow label="Movies shown" summary={optionLabel(SOURCE, store.main.kiosk_content_source)}>
			<div class="max-w-sm"><StoreField {store} {...SOURCE} input="w-full" /></div>
		</SettingRow>
		<SettingRow label="Theater name and logo" summary={shown(store.main.kiosk_header)}>
			{#snippet control()}<StoreSwitch
					{store}
					field="kiosk_header"
					label="Theater name and logo"
				/>{/snippet}
		</SettingRow>
		<SettingRow label="Clock" summary={shown(store.main.kiosk_clock)}>
			{#snippet control()}<StoreSwitch {store} field="kiosk_clock" label="Clock" />{/snippet}
		</SettingRow>
		<SettingRow
			label="Showtimes on poster tiles"
			hint="On the poster wall"
			summary={shown(store.main.kiosk_show_showtimes)}
		>
			{#snippet control()}<StoreSwitch
					{store}
					field="kiosk_show_showtimes"
					label="Showtimes on poster tiles"
				/>{/snippet}
		</SettingRow>
	</SettingList>

	<SettingList title="Taking over the screen" text="When a showing is near or live, and overnight">
		<SettingRow
			label="Now Showing card"
			hint="While a programme is live"
			summary={store.main.kiosk_takeover ? "The programme's name and artwork, full screen" : 'Off'}
		>
			{#snippet control()}<StoreSwitch
					{store}
					field="kiosk_takeover"
					label="Now Showing card"
				/>{/snippet}
		</SettingRow>
		<SettingRow label="Countdown" hint="Before the next showing" summary={countdownSummary}>
			<div class="max-w-xs">
				<StoreField
					{store}
					field="kiosk_countdown_minutes"
					label="Minutes before a showing"
					id="set-kiosk-countdown"
					hint="0 turns the countdown off."
					type="number"
					input="max-w-32"
				/>
			</div>
		</SettingRow>
		<SettingRow
			label="Night hours"
			hint="A showing still wakes it"
			summary={`${store.main.kiosk_night ? 'Dims to a clock' : 'Off'} · ${store.main.kiosk_night_start} to ${store.main.kiosk_night_end}`}
		>
			<div class="max-w-md space-y-4">
				<StoreToggle {store} field="kiosk_night" label="Dim to a clock overnight" />
				<div class="grid gap-4 sm:grid-cols-2">
					{#each NIGHT as f (f.id)}
						<StoreField {store} {...f} type="time" input={timeCls} />
					{/each}
				</div>
			</div>
		</SettingRow>
	</SettingList>
</SettingLists>
