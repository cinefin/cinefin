<script lang="ts">
	/**
	 * Title template detail = the editor itself.
	 *
	 * Unlike the programme and template detail pages, a title card has no
	 * separate read-only view. The old one was a large static preview that just
	 * sat in the way (issue #435): the editor already carries a live canvas plus
	 * a ground-truth "Render", so a card is edited straight from the listing.
	 * This route mounts the editor directly — `/titles/{id}` for an existing
	 * card, `/titles/new` for one that does not exist yet (virtual id, nothing
	 * written until the first save).
	 */
	import { page } from '$app/state';
	import { base } from '$app/paths';
	import { goto } from '$app/navigation';
	import { ArrowLeft, Trash2 } from '@lucide/svelte';
	import { api, toApiError } from '$lib/api/client';
	import { Query } from '$lib/api/query.svelte';
	import { showToast } from '$lib/toast.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import TitleEditor from '$lib/titles/TitleEditor.svelte';

	const isNew = $derived(page.params.id === 'new');
	/** NaN while `new` — every use is behind `isNew`, and no query runs. */
	const templateId = $derived(Number(page.params.id));

	// Just the name, for the heading — the editor loads the full config itself.
	// Bare-object endpoint (no envelope): read res.data directly.
	const tpl = new Query(async () => {
		const res = await api.GET('/api/v2/titlegen/templates/{template_id}', {
			params: { path: { template_id: templateId } }
		});
		if (!res.data) throw toApiError(undefined, res.response);
		return res.data;
	});

	$effect(() => {
		void templateId;
		if (isNew) return;
		void tpl.load();
	});

	let confirmDlg = $state<ConfirmDialog>();

	async function confirmAndRemove(): Promise<void> {
		if (!tpl.data) return;
		const ok = await confirmDlg?.confirm(
			`Delete “${tpl.data.name}”? Programmes using it will have no title card.`,
			{ confirmLabel: 'Delete', title: 'Delete title card' }
		);
		if (ok) await remove();
	}

	async function remove(): Promise<void> {
		try {
			const res = await api.DELETE('/api/v2/titlegen/templates/{template_id}', {
				params: { path: { template_id: templateId } }
			});
			if (res.error !== undefined && res.response.status >= 400) {
				throw toApiError(res.error, res.response);
			}
			void goto(`${base}/titles`);
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Could not delete the template', 'error');
		}
	}
</script>

<svelte:head>
	<title>{isNew ? 'New title card' : (tpl.data?.name ?? 'Title card')} - Cinefin</title>
</svelte:head>

<div class="mb-4 flex flex-wrap items-center gap-2">
	<Button href="{base}/titles" variant="ghost" size="sm">
		<ArrowLeft size={14} /> Titles
	</Button>
	<h1 class="mr-auto text-lg font-semibold">
		{isNew ? 'New title card' : (tpl.data?.name ?? 'Title card')}
	</h1>
	{#if !isNew}
		<button
			type="button"
			class="inline-flex items-center gap-1.5 text-xs text-faint transition-colors hover:text-danger"
			onclick={() => void confirmAndRemove()}
		>
			<Trash2 size={12} /> Delete title card
		</button>
	{/if}
</div>

<!-- Remount when the id changes (new → saved, or listing → listing) so the
     editor reboots against the right template; see its `booted` contract. -->
{#key page.params.id}
	<TitleEditor
		templateId={isNew ? null : templateId}
		onsaved={(id) => {
			if (isNew) void goto(`${base}/titles/${id}`);
			else void tpl.refresh();
		}}
	/>
{/key}

<ConfirmDialog bind:this={confirmDlg} />
