<script lang="ts">
	import { base } from '$app/paths';
	import { SvelteSet } from 'svelte/reactivity';
	import { FilterX, ListVideo, PenLine, Trash2, Wand2 } from '@lucide/svelte';
	import { api, toApiError, unwrap } from '$lib/api/client';
	import { query } from '$lib/api/query.svelte';
	import type { components } from '$lib/api/types.gen';
	import { sortIndicator, toggleSort, type SortSpec } from '$lib/filters';
	import { showToast } from '$lib/toast.svelte';
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

	// The list endpoint has no paging, so this fetches every programme and does
	// search and sort client-side.
	const programmes = query(() => unwrap(api.GET('/api/v2/programmes/list')));
	$effect(() => programmes.live({ keys: ['programmes'] }));

	// Signed sort key: "-name" = desc.
	const DEFAULT_SORT = '-created_at';
	let search = $state('');
	let sortKey = $state(DEFAULT_SORT);

	function clearSearch() {
		search = '';
	}

	function resetFilters() {
		clearSearch();
		sortKey = DEFAULT_SORT;
	}

	function headerSort(key: string, defaultDesc = false) {
		sortKey = toggleSort(sortKey, key, defaultDesc);
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

	const selected = new SvelteSet<number>();
	// Select-all works on what's visible: with a search active it selects the matches.
	const allSelected = $derived(filtered.length > 0 && filtered.every((p) => selected.has(p.id)));

	function toggleAll(on: boolean) {
		if (on) filtered.forEach((p) => selected.add(p.id));
		else selected.clear();
	}

	async function bulkDeleteSelected() {
		const ids = [...selected];
		if (!ids.length) return;
		const noun = ids.length === 1 ? 'programme' : 'programmes';
		const ok = await confirmDialog!.confirm(
			`Delete ${ids.length} ${noun}? This action cannot be undone.`,
			{ title: `Delete ${noun}`, confirmLabel: 'Delete' }
		);
		if (!ok) return;
		try {
			const data = await unwrap(api.POST('/api/v2/programmes/bulk-delete', { body: { ids } }));
			selected.clear();
			showToast(`Deleted ${data?.deleted ?? ids.length} ${noun}`, 'success');
			invalidate('programmes');
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Failed to delete programmes', 'error');
		}
	}

	let confirmDialog = $state<ConfirmDialog>();

	async function cueProgramme(p: Programme) {
		try {
			await unwrap(
				api.POST('/api/v2/playout/load', { body: { programme_id: p.id, generate_playlist: true } })
			);
			showToast('Programme cued - press Start playout when ready', 'success');
			void programmes.refresh(); // loading regenerates a stale playlist — clear the flag
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Failed to cue programme', 'error');
		}
	}

	async function duplicateProgramme(p: Programme) {
		try {
			const data = await unwrap(
				api.POST('/api/v2/programmes/{programme_id}/duplicate', {
					params: { path: { programme_id: p.id } }
				})
			);
			showToast(`Programme duplicated as "${data?.name ?? 'copy'}"`, 'success');
			invalidate('programmes');
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Failed to duplicate programme', 'error');
		}
	}

	async function askDelete(p: Programme) {
		const ok = await confirmDialog!.confirm(`Delete “${p.name}”? This action cannot be undone.`, {
			confirmLabel: 'Delete'
		});
		if (!ok) return;
		try {
			// Message-only response (no data envelope) — check the error branch.
			const res = await api.DELETE('/api/v2/programmes/{programme_id}', {
				params: { path: { programme_id: p.id } }
			});
			if (res.error) throw toApiError(res.error, res.response);
			selected.delete(p.id);
			showToast('Programme deleted', 'success');
			invalidate('programmes');
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Failed to delete programme', 'error');
		}
	}

	const total = $derived(programmes.data?.programmes?.length ?? 0);

	const colHeader = 'transition-colors hover:text-text';
</script>

<svelte:head><title>Programmes - Cinefin</title></svelte:head>

<div class="mb-4 flex flex-wrap items-center gap-2">
	<h1 class="mr-auto text-lg font-semibold">Programmes</h1>

	<div class="flex items-center gap-2">
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
	</div>
</div>

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
				<Button onclick={clearSearch}>Clear search</Button>
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
					checked={allSelected}
					onchange={(e) => toggleAll((e.currentTarget as HTMLInputElement).checked)}
				/>
			</div>
			<div class={POSTER_COL}></div>
			<div class={NAME_COL}>
				<button type="button" class={colHeader} onclick={() => headerSort('name')}>
					Programme {sortIndicator(sortKey, 'name')}
				</button>
			</div>
			<div class={NUM_GROUP}>
				<span class={NUM_CELL}>
					<button type="button" class={colHeader} onclick={() => headerSort('total_runtime', true)}>
						Runtime {sortIndicator(sortKey, 'total_runtime')}
					</button>
				</span>
				<span class={NUM_CELL_NARROW}>
					<button type="button" class={colHeader} onclick={() => headerSort('total_blocks', true)}>
						Items {sortIndicator(sortKey, 'total_blocks')}
					</button>
				</span>
				<span class={NUM_CELL_WIDE}>
					<button type="button" class={colHeader} onclick={() => headerSort('created_at', true)}>
						Created {sortIndicator(sortKey, 'created_at')}
					</button>
				</span>
				<span class={NUM_CELL}>
					<button
						type="button"
						class={colHeader}
						onclick={() => headerSort('last_played_at', true)}
					>
						Last played {sortIndicator(sortKey, 'last_played_at')}
					</button>
				</span>
			</div>
			<div class={ACTION_COL}></div>
		</div>

		<ul class="divide-y divide-border">
			{#each filtered as p (p.id)}
				<ProgrammeListRow
					programme={p}
					selected={selected.has(p.id)}
					onselect={(p, on) => (on ? selected.add(p.id) : selected.delete(p.id))}
					oncue={cueProgramme}
					onduplicate={duplicateProgramme}
					ondelete={askDelete}
				/>
			{/each}
		</ul>
	</div>
{/if}

<ConfirmDialog bind:this={confirmDialog} title="Delete programme" confirmLabel="Delete" />
