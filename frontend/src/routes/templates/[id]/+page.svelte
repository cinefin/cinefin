<script lang="ts">
	// Twin of the programme page: `?edit=1` swaps the read-only running order for
	// the TemplateEditor; `/templates/new` is this route with a virtual id.
	import { page } from '$app/state';
	import { base } from '$app/paths';
	import { goto } from '$app/navigation';
	import { ArrowLeft, Check, Copy, ListVideo, PanelLeftOpen, Pencil, Trash2 } from '@lucide/svelte';
	import { api, toApiError, unwrap } from '$lib/api/client';
	import { Query } from '$lib/api/query.svelte';
	import { showToast } from '$lib/toast.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import AsideToggle from '$lib/components/AsideToggle.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import TemplateEditor from '$lib/templates/TemplateEditor.svelte';
	import TemplateRundown from '$lib/templates/TemplateRundown.svelte';

	const isNew = $derived(page.params.id === 'new');
	// NaN while `new` — every use is behind `isNew`, and no query runs.
	const templateId = $derived(Number(page.params.id));

	const tpl = new Query(() =>
		unwrap(
			api.GET('/api/v2/templates/{template_id}', {
				params: { path: { template_id: templateId } }
			})
		)
	);

	$effect(() => {
		void templateId;
		if (isNew) return;
		void tpl.load();
	});

	const template = $derived(tpl.data);
	const items = $derived(template?.template?.items ?? []);
	const featureCount = $derived(template?.template?.number_of_features ?? 0);

	const editing = $derived(page.url.searchParams.get('edit') === '1');

	// Not persisted: a working mode for this visit, not a setting.
	let detailsCollapsed = $state(false);
	let autoCollapsed = false;
	$effect(() => {
		if (editing && !autoCollapsed) {
			autoCollapsed = true;
			detailsCollapsed = true;
		}
	});
	let editorDirty = $state(false);
	let editorRef = $state<TemplateEditor>();
	let confirmDlg = $state<ConfirmDialog>();

	function setEditing(on: boolean): void {
		const url = new URL(page.url);
		if (on) url.searchParams.set('edit', '1');
		else url.searchParams.delete('edit');
		void goto(url.pathname + url.search, { noScroll: true, keepFocus: true });
	}

	async function stopEditing(): Promise<void> {
		if (!editorDirty) {
			setEditing(false);
			return;
		}
		const ok = await confirmDlg?.confirm('The template has unsaved changes. Discard them?', {
			confirmLabel: 'Discard',
			title: 'Discard changes'
		});
		if (ok) discardAndStop();
	}

	function discardAndStop(): void {
		editorRef?.discardChanges();
		setEditing(false);
	}

	async function confirmDelete(): Promise<void> {
		if (!template) return;
		const ok = await confirmDlg?.confirm(
			`Delete “${template.name}”? Programmes already built from it are not affected.`,
			{ confirmLabel: 'Delete', title: 'Delete template' }
		);
		if (ok) await remove();
	}

	async function duplicate(): Promise<void> {
		try {
			const data = await unwrap(
				api.POST('/api/v2/templates/{template_id}/duplicate', {
					params: { path: { template_id: templateId } }
				})
			);
			const id = (data as unknown as { id?: number }).id;
			showToast('Template duplicated', 'success');
			if (id) void goto(`${base}/templates/${id}`);
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Could not duplicate the template', 'error');
		}
	}

	async function remove(): Promise<void> {
		try {
			const res = await api.DELETE('/api/v2/templates/{template_id}', {
				params: { path: { template_id: templateId } }
			});
			if (res.error) throw toApiError(res.error, res.response);
			void goto(`${base}/templates`);
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Could not delete the template', 'error');
		}
	}

	const segment =
		'flex h-8 min-w-0 flex-1 items-center justify-center gap-1.5 px-2 text-[0.8rem] ' +
		'font-medium whitespace-nowrap transition-colors hover:bg-surface-2';
</script>

<svelte:head>
	<title>{isNew ? 'New template' : (template?.name ?? 'Template')} - Cinefin</title>
</svelte:head>

<div class="mb-4 flex flex-wrap items-center gap-2">
	<Button href="{base}/templates" variant="ghost" size="sm">
		<ArrowLeft size={14} /> Templates
	</Button>
	{#if isNew}
		<h1 class="text-lg font-semibold">New template</h1>
	{/if}
</div>

{#if isNew}
	<div class="border border-border bg-surface-1">
		<TemplateEditor
			templateId={null}
			onsaved={(id) => void goto(`${base}/templates/${id}?edit=1`)}
		/>
	</div>
{:else if tpl.loading}
	<Spinner label="Loading template…" />
{:else if tpl.error}
	<ErrorState error={tpl.error} retry={() => void tpl.load()} />
{:else if template}
	<div class="flex flex-col gap-6 lg:flex-row lg:items-start">
		<aside
			class="min-w-0 lg:shrink-0 lg:transition-[width] lg:duration-panel lg:ease-panel
				{detailsCollapsed ? 'lg:w-14' : 'lg:w-80'}"
		>
			<!-- Collapsed: one empty frame per feature slot. -->
			<button
				type="button"
				class="hidden w-full flex-col items-center gap-2 border border-border bg-surface-1 p-2
					text-faint transition-colors hover:border-border-strong hover:text-text
					{detailsCollapsed ? 'lg:flex' : ''}"
				aria-label="Show the template details"
				title="Show the template details"
				onclick={() => (detailsCollapsed = false)}
			>
				<PanelLeftOpen size={14} aria-hidden="true" />
				{#each { length: featureCount } as _, i (i)}
					<span
						class="flex aspect-[2/3] w-full items-center justify-center border border-border
							bg-surface-2 font-mono text-[0.65rem] text-faint"
						title="Feature {i + 1}"
					>
						{i + 1}
					</span>
				{/each}
			</button>

			<section class="border border-border bg-surface-1 {detailsCollapsed ? 'lg:hidden' : ''}">
				<div class="p-4">
					<h1 class="text-xl leading-tight font-semibold">{template.name}</h1>
					{#if template.template?.description}
						<p class="mt-1.5 text-sm text-muted">{template.template.description}</p>
					{/if}
					<p class="mt-2 text-sm text-muted">
						{items.length} items
						<span class="mx-1 text-faint">·</span>
						{featureCount}
						{featureCount === 1 ? 'feature' : 'features'}
					</p>

					<Button
						variant="primary"
						class="mt-4 w-full"
						href="{base}/programmes/create"
						title="Build a programme from a template"
					>
						<ListVideo size={14} /> Create a programme
					</Button>

					<div
						class="mt-2 flex divide-x divide-border overflow-hidden rounded-md
							border border-border-strong"
					>
						<button
							type="button"
							class="{segment} {editing ? 'bg-surface-3 text-accent' : 'text-text'}"
							aria-pressed={editing}
							title={editing ? 'Stop editing this template' : 'Edit this template'}
							onclick={() => void (editing ? stopEditing() : setEditing(true))}
						>
							<Pencil size={14} /> Edit
						</button>
						<button
							type="button"
							class="{segment} text-text"
							title="Copy this template into a new one"
							onclick={() => void duplicate()}
						>
							<Copy size={14} /> Duplicate
						</button>
					</div>
				</div>

				<div class="flex justify-end border-t border-border px-4 py-2">
					<button
						type="button"
						class="inline-flex items-center gap-1.5 text-xs text-faint transition-colors
							hover:text-danger"
						onclick={() => void confirmDelete()}
					>
						<Trash2 size={12} /> Delete template
					</button>
				</div>
			</section>
		</aside>

		<div class="min-w-0 flex-1">
			<section class="border border-border bg-surface-1">
				<header
					class="flex flex-wrap items-center justify-between gap-x-4 border-b border-border px-4 py-2.5"
				>
					<div class="flex min-w-0 items-center gap-1.5">
						<AsideToggle
							collapsed={detailsCollapsed}
							label="the template details"
							ontoggle={() => (detailsCollapsed = !detailsCollapsed)}
						/>
						<h2 class="text-[0.78125rem] font-medium text-muted">Running order</h2>
					</div>
					{#if !editing}
						<span class="font-mono text-xs text-muted">
							{items.length} items · {featureCount}
							{featureCount === 1 ? 'feature' : 'features'}
						</span>
					{/if}
				</header>

				{#if editing}
					<TemplateEditor
						bind:this={editorRef}
						{templateId}
						{items}
						initialName={template.name}
						initialDescription={template.template?.description ?? ''}
						bind:dirty={editorDirty}
						onsaved={() => void tpl.refresh()}
					>
						{#snippet actions()}
							<Button size="sm" title="Stop editing" onclick={() => void stopEditing()}>
								<Check size={13} /> Done
							</Button>
						{/snippet}
					</TemplateEditor>
				{:else}
					<TemplateRundown {items} />
				{/if}
			</section>
		</div>
	</div>
{/if}

<ConfirmDialog bind:this={confirmDlg} />
