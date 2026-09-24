<script lang="ts">
	// The template editing surface: a reusable running order of abstract feature slots.
	// Twin of ProgrammeEditor — same lib/editor components, only the adapter differs.
	import type { Snippet } from 'svelte';
	import { beforeNavigate } from '$app/navigation';
	import { ApiError, api, toApiError, unwrap } from '$lib/api/client';
	import { showToast } from '$lib/toast.svelte';
	import { Eraser, Layers, Plus, Save } from '@lucide/svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import BlockList from '$lib/editor/BlockList.svelte';
	import BlockPalette from '$lib/editor/BlockPalette.svelte';
	import PickerDialog from '$lib/editor/PickerDialog.svelte';
	import ShortcutsDialog from '$lib/editor/ShortcutsDialog.svelte';
	import { BlockEditor } from '$lib/editor/editor.svelte';
	import { pickTrailerIntoBlock } from '$lib/editor/pick-actions';
	import {
		TEMPLATE_PALETTE,
		blocksToTemplateItems,
		defaultTemplateContent,
		templateBlockError,
		templateItemsToBlocks
	} from '$lib/editor/template-adapter';
	import type { EditorContext } from '$lib/editor/types';
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

	let name = $state(initialName);
	let description = $state(initialDescription);
	/** The id to PUT to: a created template keeps being edited in place. */
	let savedId = $state<number | null>(templateId);

	const editor = new BlockEditor<{ name: string; description: string }>({
		captureMeta: () => ({ name, description }),
		restoreMeta: (meta) => {
			name = meta.name;
			description = meta.description;
		}
	});

	$effect(() => {
		dirty = editor.dirty;
	});

	const featureCount = $derived(editor.blocks.filter((b) => b.type === 'feature').length);

	let bumperPicker = $state<PickerDialog>();
	let trailerPicker = $state<PickerDialog>();
	const ctx: EditorContext = $state({
		mode: 'template',
		movies: [],
		programmeMovies: [],
		commands: [],
		tags: [],
		trailerTags: [],
		genres: [],
		certifications: [],
		featureCount: 0,
		pickBumper: () => bumperPicker!.pick(),
		pickTrailer: () => trailerPicker!.pick()
	});
	$effect(() => {
		ctx.featureCount = featureCount;
	});

	let loading = $state(true);
	let loadError = $state<ApiError | null>(null);
	let booted = false;

	$effect(() => {
		if (booted) return;
		booted = true;
		void init();
	});

	async function init(): Promise<void> {
		loading = true;
		loadError = null;
		try {
			await loadReferenceLists();
			editor.reset(items.length ? templateItemsToBlocks(items, () => editor.uid()) : []);
		} catch (e) {
			loadError = toApiError(e);
		} finally {
			loading = false;
		}
	}

	async function loadReferenceLists(): Promise<void> {
		const [commands, tags, trailerTags] = await Promise.allSettled([
			unwrap(api.GET('/api/v2/commands/list')),
			unwrap(api.GET('/api/v2/media/tags', { params: { query: { per_page: 100 } } })),
			unwrap(api.GET('/api/v2/trailers/tags'))
		]);
		if (commands.status === 'fulfilled') ctx.commands = commands.value.commands;
		else console.error('Commands not available:', commands.reason);
		if (tags.status === 'fulfilled') ctx.tags = tags.value.tags;
		else console.error('Tags not available:', tags.reason);
		if (trailerTags.status === 'fulfilled')
			ctx.trailerTags = (
				trailerTags.value as unknown as { tags: { id: number; name: string }[] }
			).tags;
		else console.error('Trailer tags not available:', trailerTags.reason);
	}

	async function addItem(type: string): Promise<void> {
		const block = editor.add(type, defaultTemplateContent(type));
		scrollToBlock(editor.blocks.length - 1);
		// Trailer items go straight to the picker; cancelling keeps the item.
		if (type === 'trailer') {
			await pickTrailerIntoBlock(block, ctx, (mutate) => {
				mutate();
				editor.markDirty();
			});
		}
	}

	function scrollToBlock(index: number): void {
		setTimeout(() => {
			document
				.querySelector(`[data-block-index="${index}"]`)
				?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
		}, 50);
	}

	let confirmDialog = $state<ConfirmDialog>();

	async function removeItem(index: number): Promise<void> {
		if (!(await confirmDialog!.confirm('Are you sure you want to delete this item?'))) return;
		editor.pushUndo();
		editor.removeAt(index);
		showToast('Item deleted - press Ctrl+Z to undo', 'info');
	}

	async function clearTemplate(): Promise<void> {
		if (!editor.blocks.length && !name && !description) return;
		if (
			!(await confirmDialog!.confirm('Clear the template and start over?', {
				confirmLabel: 'Clear'
			}))
		)
			return;
		editor.pushUndo();
		name = '';
		description = '';
		editor.blocks = [];
		editor.showValidation = false;
		editor.markDirty();
		showToast('Template cleared - press Ctrl+Z to undo', 'info');
	}

	let saving = $state(false);
	const canSave = $derived(!!name.trim() && editor.blocks.length > 0);

	/** See ProgrammeEditor: the host's own discard dialog calls this first. */
	export function discardChanges(): void {
		editor.dirty = false;
	}

	export async function save(): Promise<void> {
		if (saving) return;
		if (!name.trim()) {
			showToast('Please enter a template name', 'warning');
			return;
		}
		if (editor.blocks.length === 0) {
			showToast('Template cannot be empty', 'warning');
			return;
		}
		if (featureCount === 0) {
			showToast('Add at least one Feature item', 'warning');
			return;
		}

		const invalid = editor.blocks.filter((b) => templateBlockError(b)).length;
		editor.showValidation = true;
		if (invalid > 0) {
			scrollToBlock(editor.blocks.findIndex((b) => templateBlockError(b)));
			showToast(
				`${invalid} item${invalid > 1 ? 's need' : ' needs'} attention before saving`,
				'warning'
			);
			return;
		}

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
			name: name.trim(),
			description: description.trim(),
			number_of_features: featureCount,
			items: blocksToTemplateItems(
				editor.blocks
			) as unknown as components['schemas']['CreateTemplateItemSchema'][]
		};

		saving = true;
		try {
			if (savedId === null) {
				const data = await unwrap(api.POST('/api/v2/templates/create', { body: payload }));
				editor.dirty = false;
				editor.showValidation = false;
				showToast('Template saved', 'success');
				const createdId = (data as unknown as { id?: number }).id;
				if (createdId) {
					savedId = createdId;
					onsaved?.(createdId);
				}
			} else {
				await unwrap(
					api.PUT('/api/v2/templates/{template_id}', {
						params: { path: { template_id: savedId } },
						body: payload
					})
				);
				editor.dirty = false;
				editor.showValidation = false;
				showToast('Template saved', 'success');
				onsaved?.(savedId);
			}
		} catch (e) {
			showToast(
				'Error saving template: ' + (e instanceof Error ? e.message : 'Unknown error'),
				'error'
			);
		} finally {
			saving = false;
		}
	}

	const statsText = $derived(
		`${editor.blocks.length} items · ${featureCount} feature${featureCount === 1 ? '' : 's'}`
	);

	let shortcuts = $state<ShortcutsDialog>();

	function onKeydown(e: KeyboardEvent): void {
		editor.handleKeydown(e, {
			onSave: () => {
				if (!editor.dirty) {
					showToast('No unsaved changes', 'info');
					return;
				}
				void save();
			},
			onHelp: () => shortcuts?.toggle()
		});
	}

	function onBeforeUnload(e: BeforeUnloadEvent): void {
		if (editor.dirty) e.preventDefault();
	}

	beforeNavigate((nav) => {
		if (editor.dirty && !window.confirm('You have unsaved changes. Leave without saving?')) {
			nav.cancel();
		}
	});
</script>

<svelte:window onkeydown={onKeydown} onbeforeunload={onBeforeUnload} />

{#if loading}
	<div class="p-4"><Spinner label="Loading the editor…" /></div>
{:else if loadError}
	<div class="p-4"><ErrorState error={loadError} retry={() => void init()} /></div>
{:else}
	<div class="space-y-4 p-4">
		<div class="flex flex-wrap items-end gap-3">
			<label class="flex min-w-48 flex-1 flex-col gap-1 text-sm" for="te-name">
				<span class="text-xs text-muted">Name</span>
				<Input
					id="te-name"
					placeholder="Template name"
					bind:value={name}
					oninput={() => editor.markDirty()}
				/>
			</label>
			<label class="flex min-w-56 flex-[2] flex-col gap-1 text-sm" for="te-description">
				<span class="text-xs text-muted">Description</span>
				<Input
					id="te-description"
					placeholder="Optional"
					bind:value={description}
					oninput={() => editor.markDirty()}
				/>
			</label>
		</div>

		<div class="flex flex-wrap items-center gap-2 border-t border-border pt-3">
			<span class="font-mono text-xs text-muted">{statsText}</span>
			{#if editor.dirty}
				<span class="h-2 w-2 bg-warning" title="Unsaved changes"></span>
			{/if}
			<div class="ml-auto flex flex-wrap items-center gap-2">
				<Button size="sm" onclick={() => void clearTemplate()} title="Empty the template">
					<Eraser size={13} /> Clear
				</Button>
				<Button
					size="sm"
					variant="primary"
					disabled={!canSave || saving}
					title="Save the template (Ctrl+S)"
					onclick={() => void save()}
				>
					<Save size={13} />
					{saving ? 'Saving…' : 'Save'}
				</Button>
				{#if actions}{@render actions()}{/if}
			</div>
		</div>

		<div class="flex flex-col gap-4 md:flex-row md:items-start">
			<div class="min-w-0 flex-1">
				{#if editor.blocks.length === 0}
					<EmptyState
						icon={Layers}
						title="This template is empty"
						message="Add items from the palette - a feature slot, trailer rules, idents - then drag to reorder."
						compact
					/>
				{:else}
					<BlockList {editor} {ctx} onremove={(i) => void removeItem(i)} />
				{/if}
			</div>

			<aside class="md:sticky md:top-20 md:w-52 md:shrink-0">
				<p class="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-faint">
					<Plus size={12} /> Add item
				</p>
				<BlockPalette types={TEMPLATE_PALETTE} onadd={(type) => void addItem(type)} />
			</aside>
		</div>
	</div>
{/if}

<PickerDialog kind="bumper" bind:this={bumperPicker} />
<PickerDialog kind="trailer" bind:this={trailerPicker} />
<ConfirmDialog bind:this={confirmDialog} title="Delete item?" confirmLabel="Delete" />
<ShortcutsDialog bind:this={shortcuts} />
