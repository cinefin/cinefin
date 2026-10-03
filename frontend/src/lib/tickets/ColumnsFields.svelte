<script lang="ts">
	// A columns line: how its cells split the width, adding to each cell, and the selected item's
	// own settings (pick items on the ticket). Every change goes back through `onedit`, which applies
	// it, records it and saves.
	import { ChevronDown, ChevronUp, Plus, Trash2 } from '@lucide/svelte';
	import Field from '$lib/settings/Field.svelte';
	import Menu, { type MenuItem } from '$lib/components/ui/Menu.svelte';
	import ItemFields from './ItemFields.svelte';
	import Segmented from './Segmented.svelte';
	import { COLUMN_WIDTHS, KINDS, kindOf, setField, type TicketElement } from './kinds';

	interface Props {
		el: TicketElement;
		cell?: number;
		item?: number;
		onselect: (cell?: number, item?: number) => void;
		onedit: (mutate: (el: TicketElement) => void, key?: string) => void;
	}
	let { el, cell, item, onselect, onedit }: Props = $props();

	const cells = $derived(el.cells ?? []);
	const selected = $derived(
		cell !== undefined && item !== undefined ? cells[cell]?.[item] : undefined
	);
	const iconBtn =
		'rounded-sm p-1 text-muted hover:bg-surface-3 hover:text-text disabled:pointer-events-none disabled:opacity-30';

	function setWidths(widths: number[]) {
		onedit((row) => {
			const old = row.cells ?? [];
			// Fewer cells: the dropped cell's items join the last one kept, so nothing is lost.
			const kept = old.slice(0, widths.length).map((c) => [...c]);
			while (kept.length < widths.length) kept.push([]);
			if (old.length > widths.length)
				kept[widths.length - 1].push(...old.slice(widths.length).flat());
			row.widths = widths;
			row.cells = kept;
		}, 'widths');
		if (cell !== undefined && cell >= widths.length) onselect(widths.length - 1);
	}

	function addItem(c: number, kind: string) {
		const at = cells[c].length;
		onedit((row) => row.cells![c].push(KINDS[kind].make()));
		onselect(c, at);
	}
	function moveItem(c: number, k: number, delta: number) {
		onedit((row) => {
			const list = row.cells![c];
			const [moved] = list.splice(k, 1);
			list.splice(k + delta, 0, moved);
		});
		onselect(c, k + delta);
	}
	function removeItem(c: number, k: number) {
		onedit((row) => row.cells![c].splice(k, 1));
		onselect(c);
	}

	const addItems = (c: number): MenuItem[] =>
		Object.entries(KINDS)
			.filter(([, k]) => k.inCell)
			.map(([id, k]) => ({ label: k.label, icon: k.icon, onclick: () => addItem(c, id) }));
</script>

<div class="space-y-4">
	<Field label="Cells">
		<Segmented
			label="Cell widths"
			choices={COLUMN_WIDTHS}
			value={el.widths ?? [1, 1]}
			onchange={setWidths}
		/>
	</Field>
	<div class="flex flex-wrap gap-2">
		{#each cells as _, c (c)}
			<Menu items={addItems(c)} label="Add to cell {c + 1}" icon={Plus} size="sm" />
		{/each}
	</div>

	{#if selected && cell !== undefined && item !== undefined}
		<div class="space-y-3 border-t border-border pt-4">
			<div class="flex items-center gap-1">
				<h4 class="mr-auto text-sm font-medium">
					{kindOf(selected).label}
					<span class="font-normal text-muted">in cell {cell + 1}</span>
				</h4>
				<button
					type="button"
					class={iconBtn}
					aria-label="Move up in the cell"
					disabled={item === 0}
					onclick={() => moveItem(cell, item, -1)}><ChevronUp size={15} /></button
				>
				<button
					type="button"
					class={iconBtn}
					aria-label="Move down in the cell"
					disabled={item === cells[cell].length - 1}
					onclick={() => moveItem(cell, item, 1)}><ChevronDown size={15} /></button
				>
				<button
					type="button"
					class="{iconBtn} hover:text-danger"
					aria-label="Remove from the cell"
					onclick={() => removeItem(cell, item)}><Trash2 size={15} /></button
				>
			</div>
			<ItemFields
				el={selected}
				onpatch={(key, value) =>
					onedit((row) => {
						setField(row.cells![cell][item], key, value);
					}, `cell-${cell}-${item}-${key}`)}
			/>
		</div>
	{:else}
		<p class="text-xs text-muted">
			Click an item on the ticket to edit it. A row prints as one image, its text in the design's
			font.
		</p>
	{/if}
</div>
