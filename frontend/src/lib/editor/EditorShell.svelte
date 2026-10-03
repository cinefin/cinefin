<script lang="ts">
	// The frame both running-order editors share (programme, template): name and description,
	// the toolbar, the block list beside the palette, the pickers, and the unsaved-changes guards.
	import type { Snippet } from 'svelte';
	import { beforeNavigate } from '$app/navigation';
	import { showToast } from '$lib/toast.svelte';
	import { Eraser, Plus, Save } from '@lucide/svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import BlockList from './BlockList.svelte';
	import BlockPalette from './BlockPalette.svelte';
	import PickerDialog from './PickerDialog.svelte';
	import ShortcutsDialog from './ShortcutsDialog.svelte';
	import type { EditorSession, PickerKind } from './session.svelte';
	import type { PaletteEntry } from './types';

	interface Props {
		session: EditorSession;
		stats: string;
		palette: PaletteEntry[];
		onadd: (type: string) => void;
		onsave: () => void;
		empty: Snippet;
		actions?: Snippet;
	}

	let { session, stats, palette, onadd, onsave, empty, actions }: Props = $props();

	// The session is fixed for the shell's life.
	// svelte-ignore state_referenced_locally
	const { editor, ctx } = session;
	// "programme" / "template": ids, placeholders and messages; what one row is called.
	const thing = ctx.mode;
	const programme = thing === 'programme';
	const Thing = programme ? 'Programme' : 'Template';
	const unit = programme ? 'block' : 'item';
	const Unit = programme ? 'Block' : 'Item';
	const prefix = programme ? 'pe' : 'te';
	const pickers: PickerKind[] = programme ? ['movie', 'bumper', 'trailer'] : ['bumper', 'trailer'];
	const clearTitle = programme ? 'Empty the running order' : 'Empty the template';
	const canSave = $derived(!!session.name.trim() && editor.blocks.length > 0);

	const dialogs: Partial<Record<PickerKind, PickerDialog>> = $state({});
	// svelte-ignore state_referenced_locally
	session.pick = (kind) => dialogs[kind]!.pick();

	let confirmDialog = $state<ConfirmDialog>();
	let shortcuts = $state<ShortcutsDialog>();

	async function removeBlock(index: number): Promise<void> {
		if (!(await confirmDialog!.confirm(`Are you sure you want to delete this ${unit}?`))) return;
		editor.pushUndo();
		editor.removeAt(index);
		showToast(`${Unit} deleted - press Ctrl+Z to undo`, 'info');
	}

	async function clear(): Promise<void> {
		if (!editor.blocks.length && !session.name && !session.description) return;
		const ask = `Clear the ${thing} and start over?`;
		if (!(await confirmDialog!.confirm(ask, { confirmLabel: 'Clear' }))) return;
		editor.pushUndo();
		session.name = '';
		session.description = '';
		editor.blocks = [];
		editor.showValidation = false;
		editor.markDirty();
		showToast(`${Thing} cleared - press Ctrl+Z to undo`, 'info');
	}

	function onKeydown(e: KeyboardEvent): void {
		editor.handleKeydown(e, {
			onSave: () => (editor.dirty ? onsave() : showToast('No unsaved changes', 'info')),
			onHelp: () => shortcuts?.toggle()
		});
	}

	// SPA navigations bypass beforeunload — guard them too.
	beforeNavigate((nav) => {
		if (editor.dirty && !window.confirm('You have unsaved changes. Leave without saving?')) {
			nav.cancel();
		}
	});
</script>

<svelte:window onkeydown={onKeydown} onbeforeunload={(e) => editor.dirty && e.preventDefault()} />

{#if session.loading}
	<div class="p-4"><Spinner label="Loading the editor…" /></div>
{:else if session.loadError}
	<div class="p-4"><ErrorState error={session.loadError} retry={() => session.retry()} /></div>
{:else}
	<div class="space-y-4 p-4">
		<div class="flex flex-wrap items-end gap-3">
			<label class="flex min-w-48 flex-1 flex-col gap-1 text-sm" for="{prefix}-name">
				<span class="text-xs text-muted">Name</span>
				<Input
					id="{prefix}-name"
					placeholder="{Thing} name"
					bind:value={session.name}
					oninput={() => editor.markDirty()}
				/>
			</label>
			<label class="flex min-w-56 flex-[2] flex-col gap-1 text-sm" for="{prefix}-description">
				<span class="text-xs text-muted">Description</span>
				<Input
					id="{prefix}-description"
					placeholder="Optional"
					bind:value={session.description}
					oninput={() => editor.markDirty()}
				/>
			</label>
		</div>

		<div class="flex flex-wrap items-center gap-2 border-t border-border pt-3">
			<span class="font-mono text-xs text-muted">{stats}</span>
			{#if editor.dirty}
				<span class="h-2 w-2 bg-warning" title="Unsaved changes"></span>
			{/if}
			<div class="ml-auto flex flex-wrap items-center gap-2">
				<Button size="sm" onclick={() => void clear()} title={clearTitle}>
					<Eraser size={13} /> Clear
				</Button>
				<Button
					size="sm"
					variant="primary"
					disabled={!canSave || session.saving}
					title="Save the {thing} (Ctrl+S)"
					onclick={onsave}
				>
					<Save size={13} />
					{session.saving ? 'Saving…' : 'Save'}
				</Button>
				{#if actions}{@render actions()}{/if}
			</div>
		</div>

		<div class="flex flex-col gap-4 md:flex-row md:items-start">
			<div class="min-w-0 flex-1">
				{#if editor.blocks.length === 0}
					{@render empty()}
				{:else}
					<BlockList {editor} {ctx} onremove={(i) => void removeBlock(i)} />
				{/if}
			</div>

			<aside class="md:sticky md:top-20 md:w-52 md:shrink-0">
				<p class="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-faint">
					<Plus size={12} /> Add {unit}
				</p>
				<BlockPalette types={palette} {onadd} />
			</aside>
		</div>
	</div>
{/if}

{#each pickers as kind (kind)}
	<PickerDialog {kind} bind:this={dialogs[kind]} />
{/each}
<ConfirmDialog bind:this={confirmDialog} title="Delete {unit}?" confirmLabel="Delete" />
<ShortcutsDialog bind:this={shortcuts} />
