<script lang="ts">
	// The template editing surface: a reusable running order of abstract feature slots.
	// Twin of ProgrammeEditor — same lib/editor components, only the adapter differs.
	import { onMount, type Snippet } from 'svelte';
	import { api, unwrap } from '$lib/api/client';
	import { showToast } from '$lib/toast.svelte';
	import { Layers } from '@lucide/svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import EditorShell from '$lib/editor/EditorShell.svelte';
	import { EditorSession } from '$lib/editor/session.svelte';
	import { pickTrailerIntoBlock } from '$lib/editor/pick-actions';
	import {
		TEMPLATE_PALETTE,
		blocksToTemplateItems,
		defaultTemplateContent,
		templateBlockError,
		templateItemsToBlocks
	} from '$lib/editor/template-adapter';
	import type { components } from '$lib/api/types.gen';

	type ApiItems = Parameters<typeof templateItemsToBlocks>[0];

	interface Props {
		/** null = a template that does not exist yet (save POSTs it). */
		templateId: number | null;
		/** The template's items, as the host already loaded them. */
		items?: ApiItems;
		initialName?: string;
		initialDescription?: string;
		/** Mirrors the editor's unsaved state out, for the host's own guards. */
		dirty?: boolean;
		/** After a successful save — the host refreshes what it shows. */
		onsaved?: (templateId: number) => void;
		/** Host actions for the toolbar's right-hand end (Done, Back, …). */
		actions?: Snippet;
	}

	let {
		templateId,
		items = [],
		initialName = '',
		initialDescription = '',
		dirty = $bindable(false),
		onsaved,
		actions
	}: Props = $props();

	// svelte-ignore state_referenced_locally
	const session = new EditorSession('template', templateId, initialName, initialDescription);
	const { editor, ctx } = session;

	$effect(() => {
		dirty = editor.dirty;
	});

	const featureCount = $derived(editor.blocks.filter((b) => b.type === 'feature').length);
	$effect(() => {
		ctx.featureCount = featureCount;
	});

	onMount(() => {
		void session.init(async () =>
			editor.reset(items.length ? templateItemsToBlocks(items, () => editor.uid()) : [])
		);
	});

	async function addItem(type: string): Promise<void> {
		const block = editor.add(type, defaultTemplateContent(type));
		editor.scrollTo(editor.blocks.length - 1);
		// Trailer items go straight to the picker; cancelling keeps the item.
		if (type === 'trailer') await pickTrailerIntoBlock(block, ctx, session.picked);
	}

	/** See ProgrammeEditor: the host's own discard dialog calls this first. */
	export function discardChanges(): void {
		editor.dirty = false;
	}

	export async function save(): Promise<void> {
		if (session.saving || !session.hasBasics()) return;
		if (featureCount === 0) {
			showToast('Add at least one Feature item', 'warning');
			return;
		}
		if (!session.checkBlocks(templateBlockError, 'item')) return;

		// Every feature slot the template claims must actually be assigned.
		const assigned = editor.blocks
			.filter((b) => b.type === 'feature')
			.map((b) => b.content.feature_number)
			.filter((n): n is number => !!n);
		const missing = Array.from({ length: featureCount }, (_, i) => i + 1).filter(
			(n) => !assigned.includes(n)
		);
		if (missing.length > 0) {
			showToast(
				`Add a Feature item for: ${missing.map((n) => 'Feature ' + n).join(', ')}`,
				'warning'
			);
			return;
		}

		const payload = {
			name: session.name.trim(),
			description: session.description.trim(),
			number_of_features: featureCount,
			items: blocksToTemplateItems(
				editor.blocks
			) as unknown as components['schemas']['CreateTemplateItemSchema'][]
		};

		await session.save(async () => {
			let id = session.savedId;
			if (id === null) {
				const data = await unwrap(api.POST('/api/v2/templates/create', { body: payload }));
				id = (data as unknown as { id?: number }).id || null;
			} else {
				await unwrap(
					api.PUT('/api/v2/templates/{template_id}', {
						params: { path: { template_id: id } },
						body: payload
					})
				);
			}
			session.clean();
			showToast('Template saved', 'success');
			if (id) {
				session.savedId = id;
				onsaved?.(id);
			}
		});
	}
</script>

<EditorShell
	{session}
	{actions}
	stats="{editor.blocks.length} items · {featureCount} feature{featureCount === 1 ? '' : 's'}"
	palette={TEMPLATE_PALETTE}
	onadd={(type) => void addItem(type)}
	onsave={() => void save()}
>
	{#snippet empty()}
		<EmptyState
			icon={Layers}
			title="This template is empty"
			message="Add items from the palette - a feature slot, trailer rules, idents - then drag to reorder."
			compact
		/>
	{/snippet}
</EditorShell>
