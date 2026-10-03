<script lang="ts">
	// One feature slot of the chosen template: its movie, or the buttons that fill it.
	import { ChevronDown, ChevronUp, Dices, Film, Plus } from '@lucide/svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import TypeBadge from '$lib/components/TypeBadge.svelte';
	import { itemTypeDisplay } from '$lib/item-types';
	import { itemTitle } from '$lib/programmes/create-types';
	import { rowCols, rowRuntime, slotMeta, type SlotRow } from '$lib/programmes/create-rundown';

	interface Props {
		row: SlotRow;
		slots: number;
		onchoose: () => void;
		onrandom: () => void;
		onmove: (direction: number) => void;
	}

	let { row, slots, onchoose, onrandom, onmove }: Props = $props();

	const item = $derived(row.item);
	const type = $derived(item?.kind === 'random' ? 'random_movie' : 'feature');
	const meta = $derived(itemTypeDisplay(type));
	const Icon = $derived(meta.icon);

	const iconButton =
		'rounded-sm p-1 text-faint hover:bg-surface-3 hover:text-text disabled:opacity-30 ' +
		'disabled:hover:bg-transparent disabled:hover:text-faint';
</script>

{#snippet move(dir: number, disabled: boolean, title: string, MoveIcon: typeof ChevronUp)}
	<button type="button" class={iconButton} {disabled} {title} onclick={() => onmove(dir)}>
		<MoveIcon size={14} />
	</button>
{/snippet}

<div class="flex flex-wrap items-center gap-x-3 gap-y-2 py-2.5 pl-3 {meta.classes.edge}">
	<span class={rowCols.number}>{String(row.number).padStart(2, '0')}</span>
	<Icon size={14} class="{rowCols.icon} {meta.classes.icon}" aria-hidden="true" />
	<TypeBadge {type} short col class="self-center" />

	{#if item}
		{#if item.kind === 'movie' && item.thumbnail_url}
			<img
				src={item.thumbnail_url}
				alt=""
				class="aspect-[2/3] w-16 shrink-0 border border-border object-cover sm:w-20"
			/>
		{:else}
			<div
				class="flex aspect-[2/3] w-16 shrink-0 items-center justify-center border border-border
					bg-surface-2 text-faint sm:w-20"
			>
				{#if item.kind === 'random'}<Dices size={20} />{:else}<Film size={20} />{/if}
			</div>
		{/if}

		<div class="min-w-40 flex-1">
			<p class="truncate text-sm font-medium" title={itemTitle(item)}>{itemTitle(item)}</p>
			<p class="truncate text-xs text-muted">
				{slotMeta(item)}
			</p>
			{#if item.kind === 'random'}
				<p class="truncate text-xs text-faint">Chosen when the playlist is generated</p>
			{/if}
		</div>

		<div class="ml-auto flex shrink-0 items-center gap-1">
			<Button
				size="sm"
				title="Choose a different movie for feature {row.featureNumber}"
				onclick={onchoose}
			>
				Change movie
			</Button>
			<Button
				size="sm"
				title={item.kind === 'random'
					? 'Edit this random movie’s filters'
					: 'Replace this movie with a random movie'}
				onclick={onrandom}
			>
				<Dices size={12} />
				{item.kind === 'random' ? 'Filters…' : 'Random'}
			</Button>
			{#if slots > 1}
				{@render move(-1, row.slotIndex === 0, 'Move to the slot above', ChevronUp)}
				{@render move(1, row.slotIndex === slots - 1, 'Move to the slot below', ChevronDown)}
			{/if}
		</div>
	{:else}
		<div class="flex min-w-40 flex-1 flex-wrap items-center gap-x-2 gap-y-1">
			<Button size="sm" onclick={onchoose}><Plus size={12} /> Choose a movie</Button>
			<Button
				size="sm"
				title="Fill this slot with a random movie - drawn when the playlist is generated"
				onclick={onrandom}
			>
				<Dices size={12} /> Random movie…
			</Button>
			<span class="ml-1 text-xs text-faint">
				Feature {row.featureNumber} - nothing chosen yet
			</span>
		</div>
	{/if}

	<span class={rowCols.runtime}>
		{#if row.runtime !== null}
			{rowRuntime(row.runtime, row.estimated)}
		{:else if !item}
			<Badge variant="outline">Empty</Badge>
		{:else}
			-
		{/if}
	</span>
</div>
