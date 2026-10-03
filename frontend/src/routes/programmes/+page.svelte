<script lang="ts">
	import PageHeader from '$lib/components/shell/PageHeader.svelte';
	import { base } from '$app/paths';
	import { FilterX, ListVideo, PenLine, Trash2, Wand2 } from '@lucide/svelte';
	import { api, unwrap } from '$lib/api/client';
	import { mutate } from '$lib/api/mutate';
	import { query } from '$lib/api/query.svelte';
	import type { components } from '$lib/api/types.gen';
	import { sortIndicator, toggleSort, type SortSpec } from '$lib/filters';
	import { showToast } from '$lib/toast.svelte';
	import { attempt } from '$lib/settings/form.svelte';
	import { Selection } from '$lib/selection.svelte';
	import { invalidate } from '$lib/invalidate';
	import Button from '$lib/components/ui/Button.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import BulkBar from '$lib/components/BulkBar.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import FilterBar from '$lib/components/FilterBar.svelte';
	import ProgrammeListRow from '$lib/programmes/list-row.svelte';
	import {
		ACTION_COL,
		CHECK_COL,
		NUM_CELL,
		NUM_CELL_NARROW,
		NUM_CELL_WIDE,
		NAME_COL,
		NUM_GROUP,
		POSTER_COL
	} from '$lib/programmes/list-columns';

	type Programme = components['schemas']['ProgrammeListItemSchema'];

	// No paging: search and sort are client-side.
	const programmes = query(() => unwrap(api.GET('/api/v2/programmes/list')));
	$effect(() => programmes.live({ keys: ['programmes'] }));

	const DEFAULT_SORT = '-created_at';
	let search = $state('');
	let sortKey = $state(DEFAULT_SORT);

	function resetFilters() {
		search = '';
		sortKey = DEFAULT_SORT;
	}

	const sortSpec = $derived<SortSpec>({
		value: sortKey,
		options: [
			{ value: '-created_at', label: 'Created (newest)' },
			{ value: 'created_at', label: 'Created (oldest)' },
			{ value: 'name', label: 'Name (A-Z)' },
			{ value: '-name', label: 'Name (Z-A)' },
			{ value: '-total_runtime', label: 'Runtime (longest)' },
			{ value: 'total_runtime', label: 'Runtime (shortest)' },
			{ value: '-total_blocks', label: 'Items (most)' },
			{ value: 'total_blocks', label: 'Items (fewest)' },
			{ value: '-last_played_at', label: 'Last played (recent)' },
			{ value: 'last_played_at', label: 'Last played (oldest)' }
		],
		default: DEFAULT_SORT,
		onchange: (v) => (sortKey = v)
	});

	const filtered = $derived.by(() => {
		const all = programmes.data?.programmes ?? [];
		const q = search.toLowerCase();
		const matched = q
			? all.filter(
					(p) => p.name?.toLowerCase().includes(q) || p.description?.toLowerCase().includes(q)
				)
			: [...all];

		const descending = sortKey.startsWith('-');
		const key = (descending ? sortKey.slice(1) : sortKey) as keyof Programme;
		matched.sort((a, b) => {
			if (key === 'name') {
				return (a.name || '').localeCompare(b.name || '', undefined, { sensitivity: 'base' });
			}
			const num = (p: Programme): number => {
				if (key === 'created_at' || key === 'last_played_at') {
					const v = p[key];
					return v ? Date.parse(v as string) : 0; // never played sorts last
				}
				return (p[key] as number) || 0;
			};
			return num(a) - num(b);
		});
		if (descending) matched.reverse();
		return matched;
	});

	// Select-all works on what's visible: with a search active it selects the matches.
	const selected = new Selection(() => filtered);

	async function bulkDeleteSelected() {
		const ids = [...selected];
		if (!ids.length) return;
		const noun = ids.length === 1 ? 'programme' : 'programmes';
		const ok = await confirmDialog!.confirm(
			`Delete ${ids.length} ${noun}? This action cannot be undone.`,
			{ title: `Delete ${noun}`, confirmLabel: 'Delete' }
		);
		if (!ok) return;
		await attempt(async () => {
			const data = await unwrap(api.POST('/api/v2/programmes/bulk-delete', { body: { ids } }));
			selected.clear();
			showToast(`Deleted ${data?.deleted ?? ids.length} ${noun}`, 'success');
			invalidate('programmes');
		}, 'Failed to delete programmes');
	}

	let confirmDialog = $state<ConfirmDialog>();

	async function cueProgramme(p: Programme) {
		await attempt(async () => {
			await unwrap(
				api.POST('/api/v2/playout/load', { body: { programme_id: p.id, generate_playlist: true } })
			);
			showToast('Programme cued - press Start when ready', 'success');
			void programmes.refresh(); // loading regenerates a stale playlist — clear the flag
		}, 'Failed to cue programme');
	}

	async function duplicateProgramme(p: Programme) {
		await attempt(async () => {
			const data = await unwrap(
				api.POST('/api/v2/programmes/{programme_id}/duplicate', {
					params: { path: { programme_id: p.id } }
				})
			);
			showToast(`Programme duplicated as "${data?.name ?? 'copy'}"`, 'success');
			invalidate('programmes');
		}, 'Failed to duplicate programme');
	}

	async function askDelete(p: Programme) {
		const ok = await confirmDialog!.confirm(`Delete “${p.name}”? This action cannot be undone.`, {
			confirmLabel: 'Delete'
		});
		if (!ok) return;
		await attempt(async () => {
			await mutate(
				api.DELETE('/api/v2/programmes/{programme_id}', {
					params: { path: { programme_id: p.id } }
				})
			);
			selected.delete(p.id);
			showToast('Programme deleted', 'success');
			invalidate('programmes');
		}, 'Failed to delete programme');
	}

	const total = $derived(programmes.data?.programmes?.length ?? 0);
</script>

{#snippet sortButton(label: string, key: string, defaultDesc = false)}
	<button
		type="button"
		class="transition-colors hover:text-text"
		onclick={() => (sortKey = toggleSort(sortKey, key, defaultDesc))}
	>
		{label}
		{sortIndicator(sortKey, key)}
	</button>
{/snippet}

<PageHeader title="Programmes" {actions} />
{#snippet actions()}
	<Button
		href="{base}/programmes/create"
		variant="primary"
		title="Pick your films and build from a matching template"
	>
		<Wand2 size={14} /> Guided
	</Button>
	<Button href="{base}/programmes/new" title="Start with an empty running order in the editor">
		<PenLine size={14} /> From scratch
	</Button>
{/snippet}

<FilterBar
	search={{
		value: search,
		placeholder: 'Search programmes by name or description…',
		onchange: (v) => (search = v)
	}}
	sort={sortSpec}
	count={search ? `${filtered.length} of ${total}` : `${total} total`}
	onreset={resetFilters}
/>

{#if programmes.loading}
	<Spinner label="Loading programmes…" />
{:else if programmes.error}
	<ErrorState error={programmes.error} retry={() => void programmes.load()} />
{:else if filtered.length === 0}
	{#if search}
		<EmptyState
			icon={FilterX}
			title="No programmes match your search"
			message="Try a different search, or clear it to see every programme."
		>
			{#snippet action()}
				<Button onclick={() => (search = '')}>Clear search</Button>
			{/snippet}
		</EmptyState>
	{:else}
		<EmptyState
			icon={ListVideo}
			title="No programmes yet"
			message="Build your first programme from trailers, user media and a feature — guided from your films, or from a blank running order."
		>
			{#snippet action()}
				<div class="flex items-center gap-2">
					<Button href="{base}/programmes/create" variant="primary">
						<Wand2 size={14} /> Guided
					</Button>
					<Button href="{base}/programmes/new"><PenLine size={14} /> From scratch</Button>
				</div>
			{/snippet}
		</EmptyState>
	{/if}
{:else}
	<BulkBar count={selected.size} onclear={() => selected.clear()}>
		<Button size="sm" variant="danger" onclick={bulkDeleteSelected}>
			<Trash2 size={13} /> Delete selected
		</Button>
	</BulkBar>

	<div class="border border-border bg-surface-1">
		<div
			class="hidden items-baseline gap-3 border-b border-border px-3 py-2 text-xs text-muted md:flex"
		>
			<div class={CHECK_COL}>
				<input
					type="checkbox"
					aria-label="Select all programmes"
					class="accent-accent"
					checked={selected.allVisible}
					onchange={(e) => {
						if ((e.currentTarget as HTMLInputElement).checked) selected.setVisible(true);
						else selected.clear();
					}}
				/>
			</div>
			<div class={POSTER_COL}></div>
			<div class={NAME_COL}>{@render sortButton('Programme', 'name')}</div>
			<div class={NUM_GROUP}>
				<span class={NUM_CELL}>{@render sortButton('Runtime', 'total_runtime', true)}</span>
				<span class={NUM_CELL_NARROW}>{@render sortButton('Items', 'total_blocks', true)}</span>
				<span class={NUM_CELL_WIDE}>{@render sortButton('Created', 'created_at', true)}</span>
				<span class={NUM_CELL}>{@render sortButton('Last played', 'last_played_at', true)}</span>
			</div>
			<div class={ACTION_COL}></div>
		</div>

		<ul class="divide-y divide-border">
			{#each filtered as p (p.id)}
				<ProgrammeListRow
					programme={p}
					selected={selected.has(p.id)}
					onselect={(p, on) => selected.set(p.id, on)}
					oncue={cueProgramme}
					onduplicate={duplicateProgramme}
					ondelete={askDelete}
				/>
			{/each}
		</ul>
	</div>
{/if}

<ConfirmDialog bind:this={confirmDialog} title="Delete programme" confirmLabel="Delete" />
