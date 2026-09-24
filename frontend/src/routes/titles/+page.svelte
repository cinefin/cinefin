<script lang="ts">
	import { base } from '$app/paths';
	import { goto } from '$app/navigation';
	import { Clock, Copy, Layers, PaintbrushVertical, Pencil, Plus, Trash2 } from '@lucide/svelte';
	import { api, toApiError } from '$lib/api/client';
	import { query } from '$lib/api/query.svelte';
	import type { components } from '$lib/api/types.gen';
	import { relativeTime } from '$lib/format';
	import { showToast } from '$lib/toast.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';

	type TitleTemplate = components['schemas']['TitleTemplateSchema'];

	/** Element count of a template's free-form config dict. */
	function elementCount(t: TitleTemplate): number {
		const cfg = t.template_config as { elements?: unknown[] } | null;
		return cfg?.elements?.length ?? 0;
	}

	// Primary region: the template list (bare-array endpoint, no envelope).
	const templates = query<TitleTemplate[]>(async () => {
		// 200-only endpoint: openapi-fetch types the error branch as never,
		// so a missing body is the only failure signal here.
		const res = await api.GET('/api/v2/titlegen/templates');
		if (!res.data) throw toApiError(undefined, res.response);
		return res.data;
	});

	let confirmDialog: ConfirmDialog;

	async function duplicateTemplate(t: TitleTemplate) {
		try {
			// Find a free "Name (copy)" variant — the backend rejects duplicates.
			const existing = new Set((templates.data ?? []).map((x) => x.name));
			let name = `${t.name} (copy)`;
			for (let n = 2; existing.has(name); n++) name = `${t.name} (copy ${n})`;

			const res = await api.POST('/api/v2/titlegen/templates', {
				body: {
					name,
					description: t.description,
					default_duration: t.default_duration,
					template_config: t.template_config as Record<string, never>
				}
			});
			if (res.error !== undefined || !res.data) throw toApiError(res.error, res.response);
			showToast(`Template duplicated as "${name}"`, 'success');
			void templates.refresh();
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Failed to duplicate template', 'error');
		}
	}

	async function deleteTemplate(t: TitleTemplate) {
		if (
			!(await confirmDialog.confirm(
				`Delete the template "${t.name}"? This action cannot be undone.`,
				{ confirmLabel: 'Delete' }
			))
		)
			return;
		try {
			const res = await api.DELETE('/api/v2/titlegen/templates/{template_id}', {
				params: { path: { template_id: t.id } }
			});
			if (res.error !== undefined) throw toApiError(res.error, res.response);
			showToast('Template deleted successfully', 'success');
			void templates.refresh();
		} catch (e) {
			// e.g. TEMPLATE_IN_USE when programmes still reference it.
			showToast(e instanceof Error ? e.message : 'Failed to delete template', 'error');
		}
	}

	const total = $derived(templates.data?.length ?? 0);
</script>

<svelte:head><title>Title templates - Cinefin</title></svelte:head>

<div class="mb-4 flex flex-wrap items-center gap-2">
	<h1 class="mr-2 text-lg font-semibold">Title templates</h1>
	{#if !templates.loading && !templates.error}
		<span class="mr-auto font-mono text-xs text-muted">{total} total</span>
	{:else}
		<span class="mr-auto"></span>
	{/if}
	<Button href="{base}/titles/new" variant="primary" title="Design a new title card layout">
		<Plus size={14} /> New template
	</Button>
</div>

<p class="mb-4 max-w-2xl text-sm text-muted">
	Title templates lay out generated title cards - posters, movie metadata and artwork on a 1920×1080
	canvas. Assign one to a programme from its detail page to replace the System Ident.
</p>

{#if templates.loading}
	<Spinner label="Loading templates…" />
{:else if templates.error}
	<ErrorState error={templates.error} retry={() => void templates.load()} />
{:else if !templates.data?.length}
	<EmptyState
		icon={PaintbrushVertical}
		title="No saved templates yet"
		message="Design your first title card layout - posters, titles and artwork on a 1080p canvas."
	>
		{#snippet action()}
			<Button href="{base}/titles/new" variant="primary"><Plus size={14} /> New template</Button>
		{/snippet}
	</EmptyState>
{:else}
	<div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
		{#each templates.data as t (t.id)}
			<div
				class="group flex cursor-pointer flex-col overflow-hidden rounded-lg border border-border
					bg-surface-1 transition-colors hover:border-border-strong hover:bg-surface-2"
				role="button"
				tabindex="0"
				onclick={() => void goto(`${base}/titles/${t.id}`)}
				onkeydown={(e) => {
					if (e.key === 'Enter' || e.key === ' ') {
						e.preventDefault();
						void goto(`${base}/titles/${t.id}`);
					}
				}}
			>
				<!-- Ground-truth thumbnail: the same server render that generates the
				     real card, so the listing shows the card, not an approximation.
				     ?v=updated_at busts the browser cache when a card is edited. -->
				<div class="aspect-video w-full border-b border-border bg-surface-2">
					<img
						src="/api/v2/titlegen/templates/{t.id}/preview?v={encodeURIComponent(t.updated_at)}"
						alt="{t.name} title card preview"
						loading="lazy"
						class="h-full w-full object-cover"
					/>
				</div>
				<div class="flex min-w-0 flex-col gap-2 p-4">
					<div class="flex items-start justify-between gap-2">
						<h2 class="min-w-0 truncate font-medium text-text">{t.name}</h2>
						<span class="shrink-0 font-mono text-[11px] text-faint" title={t.updated_at}>
							{relativeTime(t.updated_at)}
						</span>
					</div>
					<p class="line-clamp-2 min-h-[2lh] text-sm text-muted">
						{t.description || 'No description'}
					</p>
					<div class="flex items-center gap-4 font-mono text-xs text-muted">
						<span class="inline-flex items-center gap-1.5">
							<Layers size={12} />
							{elementCount(t)} elements
						</span>
						<span class="inline-flex items-center gap-1.5"
							><Clock size={12} /> {t.default_duration}s</span
						>
					</div>
					<div class="mt-1 flex items-center gap-2 border-t border-border pt-3">
						<Button size="sm" href="{base}/titles/{t.id}" title="Open in the editor">
							<Pencil size={13} /> Edit
						</Button>
						<Button
							size="sm"
							title="Duplicate this template"
							onclick={(e) => {
								e.stopPropagation();
								void duplicateTemplate(t);
							}}
						>
							<Copy size={13} /> Duplicate
						</Button>
						<span class="flex-1"></span>
						<Button
							size="sm"
							variant="danger"
							title="Delete this template"
							onclick={(e) => {
								e.stopPropagation();
								void deleteTemplate(t);
							}}
						>
							<Trash2 size={13} />
						</Button>
					</div>
				</div>
			</div>
		{/each}
	</div>
{/if}

<ConfirmDialog bind:this={confirmDialog} title="Delete template?" />
