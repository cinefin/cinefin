<script lang="ts" generics="M">
	import { blockError } from './display';
	import type { BlockEditor } from './editor.svelte';
	import type { EditorContext } from './types';
	import BlockCard from './BlockCard.svelte';

	interface Props {
		editor: BlockEditor<M>;
		ctx: EditorContext;
		onremove: (index: number) => void;
	}

	let { editor, ctx, onremove }: Props = $props();

	let dragIndex = $state<number | null>(null);
	let dragOverIndex = $state<number | null>(null);

	const NO_DRAG = 'button, input, select, textarea, a, label, [data-no-drag]';

	function onDragStart(e: DragEvent, index: number): void {
		if ((e.target as HTMLElement).closest(NO_DRAG)) {
			e.preventDefault();
			return;
		}
		dragIndex = index;
		e.dataTransfer!.effectAllowed = 'move';
		e.dataTransfer!.setData('text/plain', String(index)); // Firefox needs this
	}

	function onDragOver(e: DragEvent, index: number): void {
		e.preventDefault();
		e.dataTransfer!.dropEffect = 'move';
		if (index !== dragIndex) dragOverIndex = index;
	}

	function onDrop(e: DragEvent, index: number): void {
		e.preventDefault();
		dragOverIndex = null;
		if (dragIndex === null || dragIndex === index) return;
		editor.reorder(dragIndex, index);
		dragIndex = null;
	}

	function onDragEnd(): void {
		dragIndex = null;
		dragOverIndex = null;
	}
</script>

{#if editor.blocks.length > 1}
	<div class="mb-1.5 flex justify-end">
		<button
			type="button"
			class="text-xs text-muted hover:text-text"
			onclick={() => (editor.allExpanded ? editor.collapse() : editor.expandAll())}
		>
			{editor.allExpanded ? 'Collapse all' : 'Expand all'}
		</button>
	</div>
{/if}

<!-- @container: the badge/summary columns key off the PANE's width, not the
     viewport — the programme editor lives in a half-width card, the template
     editor in a full-width one. -->
<div class="@container space-y-1.5">
	{#each editor.blocks as block, i (block.uid)}
		{@const error = editor.showValidation ? blockError(block, ctx) : null}
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div
			draggable="true"
			data-block-index={i}
			class="border bg-surface-1 transition-colors
				{error ? 'border-danger/60' : editor.selected === i ? 'border-accent' : 'border-border'}
				{dragIndex === i ? 'opacity-50' : ''}
				{dragOverIndex === i ? 'border-accent-dim bg-surface-2/60' : ''}"
			ondragstart={(e) => onDragStart(e, i)}
			ondragover={(e) => onDragOver(e, i)}
			ondragleave={() => {
				if (dragOverIndex === i) dragOverIndex = null;
			}}
			ondrop={(e) => onDrop(e, i)}
			ondragend={onDragEnd}
		>
			<BlockCard {block} index={i} total={editor.blocks.length} {ctx} {editor} {error} {onremove} />
		</div>
	{/each}
</div>
