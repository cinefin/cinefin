<script lang="ts">
	// The ticket as it will print: one image the backend draws (lines that print nothing as grey
	// placeholders), with a clickable region over each line, and over each cell and item of a
	// columns line. Click to select; drag a line onto another to move it there.
	import type { Preview, Selection } from './kinds';

	interface Props {
		preview: Preview;
		selection: Selection | null;
		onselect: (selection: Selection) => void;
		onmove: (from: number, to: number) => void;
	}
	let { preview, selection, onselect, onmove }: Props = $props();

	// 1 printer dot = 0.75 px: the strip is a picture of paper, so it is sized in px, not rem.
	const SCALE = 0.75;
	const px = (dots: number) => Math.round(dots * SCALE);

	let dragFrom = $state<number | null>(null);
	let dragOver = $state<number | null>(null);

	const lineSelected = (index: number) =>
		selection?.index === index && selection?.cell === undefined;
	const itemSelected = (index: number, cell: number, item?: number) =>
		selection?.index === index && selection?.cell === cell && selection?.item === item;

	function dropClass(index: number) {
		if (dragOver !== index || dragFrom === null || dragFrom === index) return '';
		return dragFrom > index ? 'drop-above' : 'drop-below';
	}
	function onDrop(e: DragEvent, index: number) {
		e.preventDefault();
		if (dragFrom !== null && dragFrom !== index) onmove(dragFrom, index);
		dragFrom = dragOver = null;
	}
</script>

<div
	class="strip"
	style="width:{px(preview.width)}px;height:{px(preview.height)}px"
	role="list"
	aria-label="Ticket preview"
>
	<img src={preview.url} alt="" width={px(preview.width)} height={px(preview.height)} />
	{#each preview.lines as line (line.element)}
		{@const index = line.element}
		<div
			role="listitem"
			class="line {dropClass(index)}"
			style="top:{px(line.y)}px;height:{px(line.h)}px"
			draggable="true"
			ondragstart={(e) => {
				dragFrom = index;
				e.dataTransfer?.setData('text/plain', String(index));
			}}
			ondragover={(e) => {
				if (dragFrom === null) return;
				e.preventDefault();
				dragOver = index;
			}}
			ondragleave={() => {
				if (dragOver === index) dragOver = null;
			}}
			ondrop={(e) => onDrop(e, index)}
			ondragend={() => (dragFrom = dragOver = null)}
		>
			<button
				type="button"
				class="hit"
				class:selected={lineSelected(index)}
				aria-label="Line {index + 1}{line.empty ? ' (prints nothing here)' : ''}"
				aria-pressed={lineSelected(index)}
				onclick={() => onselect({ index })}
			></button>
			{#each line.cells ?? [] as cell, c (c)}
				<button
					type="button"
					class="hit"
					class:selected={itemSelected(index, c)}
					style="left:{px(cell.x)}px;width:{px(cell.w)}px"
					aria-label="Line {index + 1}, cell {c + 1}"
					onclick={() => onselect({ index, cell: c })}
				></button>
				{#each cell.items as box, k (k)}
					{#if box.h > 0}
						<button
							type="button"
							class="hit"
							class:selected={itemSelected(index, c, k)}
							style="left:{px(cell.x)}px;width:{px(cell.w)}px;top:{px(box.y - line.y)}px;height:{px(
								box.h
							)}px"
							aria-label="Line {index + 1}, cell {c + 1}, item {k + 1}"
							onclick={() => onselect({ index, cell: c, item: k })}
						></button>
					{/if}
				{/each}
			{/each}
		</div>
	{/each}
</div>

<style>
	/* The paper is deliberately paper-coloured: it previews thermal paper, not the app theme. */
	.strip {
		position: relative;
		border: 1px solid var(--color-border);
		background: #fff;
		overflow: hidden;
	}
	.strip img {
		display: block;
	}
	.line {
		position: absolute;
		left: 0;
		right: 0;
		cursor: grab;
	}
	.hit {
		position: absolute;
		inset: 0;
		border: 0;
		background: none;
		cursor: pointer;
	}
	.hit:hover {
		outline: 1px solid var(--color-border-strong);
		outline-offset: -1px;
	}
	.hit:focus-visible,
	.hit.selected {
		outline: 2px solid var(--color-accent);
		outline-offset: -2px;
	}
	.drop-above {
		box-shadow: inset 0 3px 0 var(--color-accent);
	}
	.drop-below {
		box-shadow: inset 0 -3px 0 var(--color-accent);
	}
</style>
