<script lang="ts">
	import PageHeader from '$lib/components/shell/PageHeader.svelte';
	// A title card has no read-only view (issue #435): `/titles/{id}` and `/titles/new` mount the editor.
	import { page } from '$app/state';
	import { base } from '$app/paths';
	import { goto } from '$app/navigation';
	import { Trash2 } from '@lucide/svelte';
	import { api, toApiError } from '$lib/api/client';
	import { Query } from '$lib/api/query.svelte';
	import { showToast } from '$lib/toast.svelte';
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
		if (!ok) return;
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

<PageHeader
	title={isNew ? 'New title card' : (tpl.data?.name ?? 'Title card')}
	back={{ href: `${base}/titles`, label: 'Titles' }}
	actions={isNew ? undefined : actions}
/>
{#snippet actions()}
	<button
		type="button"
		class="inline-flex items-center gap-1.5 text-xs text-faint transition-colors hover:text-danger"
		onclick={() => void confirmAndRemove()}
	>
		<Trash2 size={12} /> Delete title card
	</button>
{/snippet}

<!-- The editor loads one template per mount, so remount it when the id changes. -->
{#key page.params.id}
	<TitleEditor
		templateId={isNew ? null : templateId}
		onsaved={(id) => void goto(`${base}/titles/${id}`)}
	/>
{/key}

<ConfirmDialog bind:this={confirmDlg} />
