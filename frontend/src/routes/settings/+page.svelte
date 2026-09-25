<script lang="ts">
	import { display } from '$lib/display.svelte';
	import {
		Check,
		Database,
		Film,
		Lock,
		Palette,
		Play,
		Puzzle,
		RotateCcw,
		Server,
		Ticket,
		Tv
	} from '@lucide/svelte';
	import type { Component } from 'svelte';
	import type { LucideIcon } from '@lucide/svelte';
	import { page } from '$app/state';
	import { replaceState } from '$app/navigation';
	import { api } from '$lib/api/client';
	import { mutate } from '$lib/api/mutate';
	import { showToast } from '$lib/toast.svelte';
	import { SettingsStore, formatStamp } from '$lib/settings/form.svelte';
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

	type Section =
		| 'playout'
		| 'cinema'
		| 'tickets'
		| 'kiosk'
		| 'library'
		| 'appearance'
		| 'plugins'
		| 'security'
		| 'backup';

	interface NavItem {
		id: Section;
		label: string;
		icon: LucideIcon;
	}
	const NAV: { group: string; items: NavItem[] }[] = [
		{
			group: 'Core',
			items: [
				{ id: 'playout', label: 'Playout', icon: Play },
				{ id: 'cinema', label: 'Theater', icon: Film },
				{ id: 'tickets', label: 'Tickets', icon: Ticket }
			]
		},
		{
			group: 'Content',
			items: [
				{ id: 'kiosk', label: 'Kiosk display', icon: Tv },
				{ id: 'library', label: 'Library source', icon: Server }
			]
		},
		{
			group: 'System',
			items: [
				{ id: 'appearance', label: 'Appearance', icon: Palette },
				{ id: 'plugins', label: 'Plugins', icon: Puzzle },
				{ id: 'security', label: 'Security', icon: Lock },
				{ id: 'backup', label: 'Backup & restore', icon: Database }
			]
		}
	];
	const ALL_SECTIONS = NAV.flatMap((g) => g.items.map((i) => i.id));

	const initialTab = page.url.searchParams.get('tab');
	let section = $state<Section>(
		ALL_SECTIONS.includes(initialTab as Section) ? (initialTab as Section) : 'playout'
	);

	function goSection(id: Section) {
		section = id;
		const url = new URL(page.url);
		url.searchParams.set('tab', id);
		replaceState(url, {});
	}

	const HEADINGS: Record<Section, { title: string; blurb: string }> = {
		playout: {
			title: 'Playout',
			blurb: 'The machine at the screen, its picture and sound, and what plays around a programme.'
		},
		cinema: {
			title: 'Theater',
			blurb: "Your theater's identity and the certification cards shown before features."
		},
		tickets: {
			title: 'Tickets',
			blurb: 'Auditorium size, the thermal printer, and reusable ticket designs.'
		},
		kiosk: {
			title: 'Kiosk display',
			blurb: 'Defaults for every kiosk screen; each display can still override them.'
		},
		library: {
			title: 'Library source',
			blurb: 'The one media server your films come from, and the TMDB key that enriches them.'
		},
		appearance: {
			title: 'Appearance',
			blurb: 'How the web app looks - the navbar logo, accent colour and clock format.'
		},
		plugins: {
			title: 'Plugins',
			blurb: 'The kinds of action your commands can run, and the connection settings they need.'
		},
		security: {
			title: 'Security',
			blurb: 'Require a login to reach Cinefin, and mint API keys for programmatic access.'
		},
		backup: {
			title: 'Backup & restore',
			blurb:
				'Save a complete copy of your Cinefin database, and restore it if something goes wrong.'
		}
	};

	async function save() {
		const result = await store.save();
		if (result.ok) {
			showToast('Settings saved', 'success');
		} else {
			if (result.section) goSection(result.section as Section);
			showToast(result.message || 'Failed to save settings', 'error');
		}
	}

	async function discard() {
		await store.load();
		showToast('Changes discarded', 'info');
	}

	async function reset() {
		if (
			!(await confirm('Reset all settings to their defaults? This cannot be undone.', {
				confirmLabel: 'Reset'
			}))
		) {
			return;
		}
		try {
			await mutate(api.POST('/api/v2/settings/reset/'));
			showToast('Settings reset to defaults', 'success');
			await store.load();
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Failed to reset settings', 'error');
		}
	}
</script>

<svelte:head><title>Settings - Cinefin</title></svelte:head>

<ConfirmDialog bind:this={confirmDialog} />

<div class="mb-4 flex flex-wrap items-center gap-2">
	<h1 class="mr-auto text-lg font-semibold">Settings</h1>
</div>

{#if store.loading}
	<Spinner label="Loading settings…" />
{:else if store.error}
	<ErrorState error={store.error} retry={() => void store.load()} />
{:else}
	<div class="flex flex-col gap-6 pb-24 lg:flex-row">
		<nav class="shrink-0 lg:w-52" aria-label="Settings sections">
			<div class="flex flex-row flex-wrap gap-1 lg:flex-col lg:gap-4">
				{#each NAV as group (group.group)}
					<div class="min-w-0">
						<div class="mb-1 hidden px-2 text-[0.65rem] font-medium text-faint lg:block">
							{group.group}
						</div>
						<div class="flex flex-row flex-wrap gap-1 lg:flex-col">
							{#each group.items as item (item.id)}
								<button
									type="button"
									class="flex items-center gap-2 rounded-md px-2.5 py-1.5 text-sm transition-colors
										{section === item.id
										? 'bg-surface-2 font-medium text-accent'
										: 'text-muted hover:bg-surface-1 hover:text-text'}"
									aria-current={section === item.id ? 'page' : undefined}
									onclick={() => goSection(item.id)}
								>
									<item.icon size={15} class="shrink-0" />
									{item.label}
								</button>
							{/each}
						</div>
					</div>
				{/each}
			</div>
			<p class="mt-4 hidden px-2 text-xs text-faint lg:block">
				Last saved {formatStamp(store.updatedAt)}
			</p>
		</nav>

		<div class="min-w-0 flex-1">
			<header class="mb-4">
				<h2 class="text-base font-medium">
					{HEADINGS[section].title}
				</h2>
				<p class="mt-1 max-w-3xl text-sm text-muted">{HEADINGS[section].blurb}</p>
			</header>

			{#if section === 'playout'}
				<PlayoutSection {store} {confirm} />
			{:else if section === 'cinema'}
				<CinemaSection {store} />
			{:else if section === 'tickets'}
				<TicketsSection {store} {confirm} />
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
				<BackupSection {confirm} />
			{/if}
		</div>
	</div>

	<div
		class="fixed right-0 bottom-0 left-0 z-20 border-t border-border bg-surface-1 {display.rail
			? 'md:left-14'
			: 'md:left-56'}"
	>
		<div class="flex items-center gap-2 px-4 py-2.5">
			<Button variant="danger" onclick={reset}>
				<RotateCcw size={14} /> Reset to defaults
			</Button>
			<span class="flex-1"></span>
			{#if store.dirtyCount}
				<span class="text-xs text-warning">
					{store.dirtyCount} unsaved change{store.dirtyCount === 1 ? '' : 's'}
				</span>
			{/if}
			<Button disabled={!store.dirtyCount || store.saving} onclick={discard}>
				Discard changes
			</Button>
			<Button variant="primary" disabled={store.saving} onclick={save}>
				<Check size={14} />
				{store.saving ? 'Saving…' : 'Save changes'}
			</Button>
		</div>
	</div>
{/if}
