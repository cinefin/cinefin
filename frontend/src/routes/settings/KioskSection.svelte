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

	const BETWEEN = storeField('kiosk_between', 'Show', 'set-kiosk-between', {
		options: [
			['whats_on', "What's on: the next screening, then the three after it"],
			['screenings', 'Screenings in turn'],
			['films', 'Films in turn'],
			['week', 'This week: every screening as a list']
		]
	});
	const ROTATE = storeField('kiosk_rotate_seconds', 'Each for', 'set-kiosk-rotate', {
		hint: 'For screenings or films in turn.',
		options: [8, 15, 30, 60].map((n) => [String(n), `${n} seconds`] as const)
	});
	const SOURCE = storeField('kiosk_content_source', 'Films', 'set-kiosk-source', {
		hint: "Flag films with the library's kiosk switch.",
		options: [
			['flagged', 'Films flagged for the kiosk'],
			['all', 'The whole library'],
			['scheduled', 'Only films with screenings booked']
		]
	});
	const DOORS = storeField('kiosk_doors_minutes', 'Doors open', 'set-kiosk-doors', {
		options: [
			['0', 'Off'],
			...[10, 15, 20, 30, 45, 60].map((n) => [String(n), `${n} minutes before`] as const)
		]
	});
	const NIGHT = [
		storeField('kiosk_night_start', 'Quiet from', 'set-kiosk-night-start'),
		storeField('kiosk_night_end', 'Until', 'set-kiosk-night-end')
	];

	const turns = $derived(['screenings', 'films'].includes(store.main.kiosk_between));
	const betweenSummary = $derived(
		optionLabel(BETWEEN, store.main.kiosk_between).split(':')[0] +
			(turns ? ` · ${store.main.kiosk_rotate_seconds} seconds each` : '')
	);
</script>

<SettingLists>
	<SettingList title="Between screenings" text="A kiosk picks changes up within a few minutes">
		{#snippet actions()}
			<Button size="sm" href="{base}/kiosk" title="Open the kiosk">
				<ExternalLink size={13} /> Open the kiosk
			</Button>
		{/snippet}
		<SettingRow label="Show" summary={betweenSummary}>
			<div class="grid max-w-xl gap-4 sm:grid-cols-2">
				<StoreField {store} {...BETWEEN} input="w-full" />
				{#if turns}<StoreField {store} {...ROTATE} input="w-full" />{/if}
			</div>
		</SettingRow>
		<SettingRow
			label="Films"
			hint="For films in turn"
			summary={optionLabel(SOURCE, store.main.kiosk_content_source)}
		>
			<div class="max-w-sm"><StoreField {store} {...SOURCE} input="w-full" /></div>
		</SettingRow>
		<SettingRow label="Clock" summary={store.main.kiosk_clock ? 'Shown' : 'Hidden'}>
			{#snippet control()}<StoreSwitch {store} field="kiosk_clock" label="Clock" />{/snippet}
		</SettingRow>
		<SettingRow
			label="Night hours"
			hint="Dims between screenings"
			summary={store.main.kiosk_night
				? `${store.main.kiosk_night_start} to ${store.main.kiosk_night_end}`
				: 'Off'}
		>
			<div class="max-w-md space-y-4">
				<StoreToggle {store} field="kiosk_night" label="Dim overnight" />
				<div class="grid gap-4 sm:grid-cols-2">
					{#each NIGHT as f (f.id)}
						<StoreField {store} {...f} type="time" input={timeCls} />
					{/each}
				</div>
			</div>
		</SettingRow>
	</SettingList>

	<SettingList title="Around a screening" text="On air takes over while a programme plays">
		<SettingRow
			label="Doors open"
			hint="The screening, large, with its start time"
			summary={optionLabel(DOORS, store.main.kiosk_doors_minutes)}
		>
			<div class="max-w-xs"><StoreField {store} {...DOORS} input="w-full" /></div>
		</SettingRow>
	</SettingList>
</SettingLists>
