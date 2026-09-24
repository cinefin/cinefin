<script lang="ts">
	import { Copy, FilterX, Layers, Pencil, Plus, Trash2 } from '@lucide/svelte';
	import { base } from '$app/paths';
	import { api, toApiError, unwrap } from '$lib/api/client';
	import { query } from '$lib/api/query.svelte';
	import { sortRows } from '$lib/filters';
	import type { components } from '$lib/api/types.gen';
	import { showToast } from '$lib/toast.svelte';
	import SortHeader from '$lib/components/SortHeader.svelte';
	import { templateBreakdown } from '$lib/programmes/create-types';
	import Button from '$lib/components/ui/Button.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';

	type TemplateSummary = components['schemas']['TemplateSummarySchema'];

	const templates = query(() =>
		unwrap(api.GET('/api/v2/templates/list', { params: { query: { per_page: 100 } } }))
	);

	let searchInput = $state('');
	let search = $state('');
	let debounceTimer: ReturnType<typeof setTimeout> | undefined;
	function onSearchInput() {
		clearTimeout(debounceTimer);
		debounceTimer = setTimeout(() => (search = searchInput), 300);
	}
	function clearSearch() {
		searchInput = '';
		search = '';
	}

	const filtered = $derived.by(() => {
		const all = templates.data?.templates ?? [];
		const q = search.toLowerCase();
		if (!q) return all;
		return all.filter(
			(t) => t.name.toLowerCase().includes(q) || t.description.toLowerCase().includes(q)
		);
	});

	let sort = $state('');
	const sorted = $derived(
		sortRows(filtered, sort, {
			name: (t) => t.name.toLowerCase(),
			features: (t) => t.number_of_features,
			created: (t) => t.created_at
		})
	);

	let confirmDialog = $state<ConfirmDialog>();

	async function duplicateTemplate(t: TemplateSummary): Promise<void> {
		try {
			await unwrap(
				api.POST('/api/v2/templates/{template_id}/duplicate', {
					params: { path: { template_id: t.id } }
				})
			);
			showToast('Template duplicated', 'success');
			void templates.refresh();
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Failed to duplicate template', 'error');
		}
	}

	async function deleteTemplate(t: TemplateSummary): Promise<void> {
		if (
			!(await confirmDialog!.confirm(`Delete “${t.name}”? This cannot be undone.`, {
				confirmLabel: 'Delete'
			}))
		)
			return;
		try {
			// Message-only response (no data envelope) — check the error branch.
			const res = await api.DELETE('/api/v2/templates/{template_id}', {
				params: { path: { template_id: t.id } }
			});
			if (res.error) throw toApiError(res.error, res.response);
			showToast('Template deleted', 'success');
			void templates.refresh();
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Failed to delete template', 'error');
		}
	}

	const iconBtn =
		'inline-flex h-7 w-7 items-center justify-center rounded-md border border-border-strong ' +
		'bg-surface-2 text-muted transition-colors hover:bg-surface-3 hover:text-text';
</script>

<svelte:head><title>Templates - Cinefin</title></svelte:head>

<div class="mb-4 flex flex-wrap items-center gap-2">
	<h1 class="mr-2 text-lg font-semibold">Templates</h1>
	{#if !templates.loading && !templates.error}
		<span class="mr-auto font-mono text-xs text-muted">
			{templates.data?.templates?.length ?? 0} total
		</span>
	{:else}
		<span class="mr-auto"></span>
	{/if}
	<Button
		href="{base}/templates/new"
		variant="primary"
		title="Build a reusable running-order structure"
	>
		<Plus size={14} /> New template
	</Button>
</div>

<div class="mb-4 flex flex-wrap items-center gap-2">
	<Input
		type="search"
		placeholder="Search templates by name or description…"
		bind:value={searchInput}
		oninput={onSearchInput}
		class="w-full sm:w-72"
	/>
	{#if search}
		<Button variant="ghost" onclick={clearSearch} title="Clear search">
			<FilterX size={14} /> Reset
		</Button>
	{/if}
</div>

{#if templates.loading}
	<Spinner label="Loading templates…" />
{:else if templates.error}
	<ErrorState error={templates.error} retry={() => void templates.load()} />
{:else if filtered.length === 0}
	{#if search}
		<EmptyState
			icon={FilterX}
			title="No templates match your search"
			message="Try a different search, or clear it to see every template."
		>
			{#snippet action()}
				<Button onclick={clearSearch}>Clear search</Button>
			{/snippet}
		</EmptyState>
	{:else}
		<EmptyState
			icon={Layers}
			title="No templates yet"
			message="A template defines a reusable running order - trailers, user media and feature slots - that programmes are built from."
		>
			{#snippet action()}
				<Button href="{base}/templates/new" variant="primary">New template</Button>
			{/snippet}
		</EmptyState>
	{/if}
{:else}
	<div class="overflow-x-auto rounded-lg border border-border bg-surface-1">
		<table class="w-full text-sm">
			<thead>
				<tr class="border-b border-border bg-surface-2 text-left text-xs font-medium text-muted">
					<SortHeader {sort} col="name" label="Template" onsort={(s) => (sort = s)} />
					<SortHeader
						{sort}
						col="features"
						label="Features"
						defaultDesc
						onsort={(s) => (sort = s)}
					/>
					<th class="px-3 py-2">Structure</th>
					<SortHeader
						{sort}
						col="created"
						label="Created"
						defaultDesc
						class="hidden lg:table-cell"
						onsort={(s) => (sort = s)}
					/>
					<th class="px-3 py-2 text-right">Actions</th>
				</tr>
			</thead>
			<tbody class="divide-y divide-border">
				{#each sorted as t (t.id)}
					<tr class="align-top hover:bg-surface-2/50">
						<td class="max-w-64 px-3 py-3">
							<a href="{base}/templates/{t.id}" class="group block">
								<span class="font-medium group-hover:text-accent">{t.name}</span>
								{#if t.description}
									<span class="mt-0.5 block truncate text-xs text-muted">{t.description}</span>
								{/if}
							</a>
						</td>
						<td class="px-3 py-3 font-mono">{t.number_of_features}</td>
						<td class="max-w-80 px-3 py-3 text-muted">{templateBreakdown(t)}</td>
						<td class="hidden px-3 py-3 whitespace-nowrap text-muted lg:table-cell">
							{new Date(t.created_at).toLocaleDateString()}
						</td>
						<td class="px-3 py-3">
							<div class="flex justify-end gap-1.5">
								<a class={iconBtn} href="{base}/templates/{t.id}?edit=1" title="Edit">
									<Pencil size={13} />
								</a>
								<button
									type="button"
									class={iconBtn}
									title="Duplicate"
									onclick={() => void duplicateTemplate(t)}
								>
									<Copy size={13} />
								</button>
								<button
									type="button"
									class="{iconBtn} hover:text-danger"
									title="Delete"
									onclick={() => void deleteTemplate(t)}
								>
									<Trash2 size={13} />
								</button>
							</div>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{/if}

<ConfirmDialog bind:this={confirmDialog} title="Delete template?" confirmLabel="Delete" />
