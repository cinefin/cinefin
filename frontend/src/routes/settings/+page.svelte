<script lang="ts">
	import PageHeader from '$lib/components/shell/PageHeader.svelte';
	import { Check, RotateCcw } from '@lucide/svelte';
	import { page } from '$app/state';
	import { beforeNavigate } from '$app/navigation';
	import { onDestroy, untrack } from 'svelte';
	import { AutoSave } from '$lib/settings/autosave.svelte';
	import SaveState from '$lib/settings/SaveState.svelte';
	import { SETTINGS_SECTIONS, settingsSectionOf } from '$lib/settings/sections';
	import SettingsToolbar from './SettingsToolbar.svelte';
	import { api } from '$lib/api/client';
	import { mutate } from '$lib/api/mutate';
	import { showToast } from '$lib/toast.svelte';
	import { SettingsStore, attempt, formatStamp } from '$lib/settings/form.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import AppearanceSection from './AppearanceSection.svelte';
	import BackupSection from './BackupSection.svelte';
	import CinemaSection from './CinemaSection.svelte';
	import PluginsSection from './PluginsSection.svelte';
	import KioskSection from './KioskSection.svelte';
	import LibrarySourceSection from './LibrarySourceSection.svelte';
	import PlayoutSection from './PlayoutSection.svelte';
	import SecuritySection from './SecuritySection.svelte';
	import TicketsSection from './TicketsSection.svelte';

	const store = new SettingsStore();
	void store.load();

	let confirmDialog: ConfirmDialog;
	const confirm = (text: string, opts?: { confirmLabel?: string }) =>
		confirmDialog.confirm(text, opts);

	// The toolbar's sections are ?tab= links; the page follows the URL, so a link to another
	// section while already here (the health menu) just switches it.
	const section = $derived(settingsSectionOf(page.url));
	// Sections laid out as SettingLists (they go side by side when there is room).
	const FULL_WIDTH = new Set(['playout', 'library', 'cinema', 'tickets', 'kiosk']);
	const current = $derived(SETTINGS_SECTIONS.find((s) => s.id === section)!);

	// Every change saves itself a moment later; leaving the page saves what is waiting.
	const saver = new AutoSave(async () => {
		const result = await store.save();
		if (!result.ok) {
			showToast(result.message || 'Failed to save settings', 'error');
			throw new Error(result.message);
		}
	});
	$effect(() => {
		void store.signature;
		if (untrack(() => store.dirtyCount)) saver.schedule();
	});
	beforeNavigate(() => {
		if (saver.waiting) void saver.flush();
	});
	onDestroy(() => {
		if (saver.waiting) void saver.flush();
	});

	async function reset() {
		const ok = await confirm('Reset all settings to their defaults? This cannot be undone.', {
			confirmLabel: 'Reset'
		});
		if (!ok) return;
		await attempt(async () => {
			await mutate(api.POST('/api/v2/settings/reset/'));
			saver.cancel();
			showToast('Settings reset to defaults', 'success');
			await store.load();
		}, 'Failed to reset settings');
	}
</script>

<ConfirmDialog bind:this={confirmDialog} />

<PageHeader title="Settings" {actions} />
{#snippet actions()}
	{#if !store.loading && !store.error}
		<SaveState {saver} idle="Changes save as you make them" />
		{#if store.canUndo && saver.status === 'saved'}
			<Button size="sm" variant="ghost" onclick={() => store.undo()}>Undo</Button>
		{/if}
	{/if}
{/snippet}

<SettingsToolbar current={section} />

{#if store.loading}
	<Spinner label="Loading settings…" />
{:else if store.error}
	<ErrorState error={store.error} retry={() => void store.load()} />
{:else}
	<div class="pb-8">
		<p class="mb-5 max-w-3xl text-sm text-muted">{current.blurb}</p>

		<!-- Sections built from SettingLists fill the page; the older field groups keep a reading width. -->
		<div class={FULL_WIDTH.has(section) ? '' : 'max-w-5xl'}>
			{#if section === 'playout'}
				<PlayoutSection {store} {confirm} />
			{:else if section === 'cinema'}
				<CinemaSection {store} />
			{:else if section === 'tickets'}
				<TicketsSection {store} />
			{:else if section === 'kiosk'}
				<KioskSection {store} />
			{:else if section === 'library'}
				<LibrarySourceSection {store} {confirm} />
			{:else if section === 'appearance'}
				<AppearanceSection {store} {confirm} />
			{:else if section === 'plugins'}
				<PluginsSection />
			{:else if section === 'security'}
				<SecuritySection {confirm} />
			{:else if section === 'backup'}
				<BackupSection {confirm} onreset={reset} />
			{/if}
		</div>
	</div>
{/if}
