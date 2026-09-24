<script lang="ts">
	import { fade } from 'svelte/transition';
	import { ExternalLink } from '@lucide/svelte';
	import { base } from '$app/paths';
	import type { SettingsStore } from '$lib/settings/form.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Tabs from '$lib/components/ui/Tabs.svelte';
	import Field from './Field.svelte';
	import Toggle from '$lib/components/ui/Toggle.svelte';

	interface Props {
		store: SettingsStore;
	}
	let { store }: Props = $props();

	const TABS = [
		{ id: 'layout', label: 'Layout' },
		{ id: 'chrome', label: 'Chrome' },
		{ id: 'takeovers', label: 'Takeovers' }
	];
	let tab = $state('layout');
</script>

<div class="mb-4 flex flex-wrap items-center gap-3">
	<Button href="{base}/kiosk" title="Open the kiosk display">
		<ExternalLink size={14} /> Open kiosk
	</Button>
	<p class="text-xs text-faint">
		A live kiosk picks saved changes up within a few minutes on its own refresh.
	</p>
</div>

<Tabs
	tabs={TABS}
	value={tab}
	label="Kiosk settings"
	onselect={(id) => (tab = id)}
	panelId={(id) => `kt-${id}`}
/>

{#if tab === 'layout'}
	<div
		role="tabpanel"
		id="kt-layout"
		aria-labelledby="tab-layout"
		class="mt-4 grid gap-4 sm:grid-cols-2"
		in:fade={{ duration: 120 }}
	>
		<Field
			label="Layout"
			forId="set-kiosk-layout"
			dirty={store.isDirty('kiosk_layout')}
			error={store.errorFor('kiosk_layout')}
		>
			<Select id="set-kiosk-layout" bind:value={store.main.kiosk_layout} class="w-full">
				<option value="wall">Poster wall</option>
				<option value="spotlight">Spotlight</option>
				<option value="split">Split (spotlight + showings)</option>
				<option value="board">Schedule board</option>
				<option value="tonight">Tonight (next showing only)</option>
				<option value="auto">Auto (picks by schedule)</option>
			</Select>
		</Field>
		<Field
			label="Rotate layouts"
			forId="set-kiosk-rotate"
			hint="Cycles the ambient layouts (wall, spotlight, split). Ignored while the layout is Auto."
			dirty={store.isDirty('kiosk_rotate_minutes')}
			error={store.errorFor('kiosk_rotate_minutes')}
		>
			<Select id="set-kiosk-rotate" bind:value={store.main.kiosk_rotate_minutes} class="w-full">
				<option value="0">Off</option>
				<option value="2">Every 2 minutes</option>
				<option value="5">Every 5 minutes</option>
				<option value="10">Every 10 minutes</option>
				<option value="15">Every 15 minutes</option>
				<option value="30">Every 30 minutes</option>
				<option value="60">Every hour</option>
			</Select>
		</Field>
		<Field
			label="Movies shown"
			forId="set-kiosk-source"
			hint="Flag movies from the library's kiosk toggle."
			dirty={store.isDirty('kiosk_content_source')}
			error={store.errorFor('kiosk_content_source')}
		>
			<Select id="set-kiosk-source" bind:value={store.main.kiosk_content_source} class="w-full">
				<option value="flagged">Movies flagged for the kiosk</option>
				<option value="all">The whole library</option>
				<option value="scheduled">Only movies with upcoming showings</option>
			</Select>
		</Field>
	</div>
{:else if tab === 'chrome'}
	<div
		role="tabpanel"
		id="kt-chrome"
		aria-labelledby="tab-chrome"
		class="mt-4 max-w-xl space-y-2.5"
		in:fade={{ duration: 120 }}
	>
		<Toggle
			label="Theater name / logo header"
			bind:checked={store.main.kiosk_header}
			dirty={store.isDirty('kiosk_header')}
		/>
		<Toggle
			label="Clock"
			bind:checked={store.main.kiosk_clock}
			dirty={store.isDirty('kiosk_clock')}
		/>
		<Toggle
			label="Showtimes on poster-wall tiles"
			bind:checked={store.main.kiosk_show_showtimes}
			dirty={store.isDirty('kiosk_show_showtimes')}
		/>
	</div>
{:else if tab === 'takeovers'}
	<div
		role="tabpanel"
		id="kt-takeovers"
		aria-labelledby="tab-takeovers"
		class="mt-4 max-w-xl space-y-4"
		in:fade={{ duration: 120 }}
	>
		<Toggle
			label="Now Showing takeover"
			hint="While a programme is live the kiosk switches to a full-screen Now Showing card - the programme's name and artwork - then returns to its layout when the show ends."
			bind:checked={store.main.kiosk_takeover}
			dirty={store.isDirty('kiosk_takeover')}
		/>
		<Field
			label="Countdown threshold (min)"
			forId="set-kiosk-countdown"
			hint="Full-screen countdown when the next showing is this close. 0 turns it off."
			dirty={store.isDirty('kiosk_countdown_minutes')}
			error={store.errorFor('kiosk_countdown_minutes')}
		>
			<Input
				id="set-kiosk-countdown"
				type="number"
				bind:value={store.main.kiosk_countdown_minutes}
				class="max-w-32"
			/>
		</Field>

		<div class="mt-6 border-t border-border pt-5">
			<h3 class="mb-3 text-[0.78125rem] font-medium text-muted">Night hours</h3>
			<div class="space-y-4">
				<Toggle
					label="Dim to a clock overnight"
					bind:checked={store.main.kiosk_night}
					dirty={store.isDirty('kiosk_night')}
				/>
				<div class="grid max-w-md gap-4 sm:grid-cols-2">
					<Field
						label="Quiet from"
						forId="set-kiosk-night-start"
						dirty={store.isDirty('kiosk_night_start')}
						error={store.errorFor('kiosk_night_start')}
					>
						<input
							id="set-kiosk-night-start"
							type="time"
							bind:value={store.main.kiosk_night_start}
							class="h-9 w-full rounded-md border border-border-strong bg-surface-2 px-3 text-sm text-text focus:border-accent-dim"
						/>
					</Field>
					<Field
						label="Until"
						forId="set-kiosk-night-end"
						dirty={store.isDirty('kiosk_night_end')}
						error={store.errorFor('kiosk_night_end')}
					>
						<input
							id="set-kiosk-night-end"
							type="time"
							bind:value={store.main.kiosk_night_end}
							class="h-9 w-full rounded-md border border-border-strong bg-surface-2 px-3 text-sm text-text focus:border-accent-dim"
						/>
					</Field>
				</div>
				<p class="text-xs text-faint">
					A live programme or an imminent showing wakes the display regardless.
				</p>
			</div>
		</div>
	</div>
{/if}
