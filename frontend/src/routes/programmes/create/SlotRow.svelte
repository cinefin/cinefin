<script lang="ts">
	// The empty-slot branch is a defensive fallback: a template is only offered
	// when it takes exactly the features already chosen.
	import { ChevronDown, ChevronUp, Dices, Film, Plus } from '@lucide/svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import TypeBadge from '$lib/components/TypeBadge.svelte';
	import { itemTypeDisplay } from '$lib/item-types';
	import { canChooseTracks, itemTitle, trackSummary } from '$lib/programmes/create-types';
	import { rowCols, rowRuntime, slotMeta, type SlotRow } from '$lib/programmes/create-rundown';

	interface Props {
		row: SlotRow;
		slots: number;
		onchoose: () => void;
		onrandom: () => void;
		ontracks: () => void;
		onmove: (direction: number) => void;
	}

	let { row, slots, onchoose, onrandom, ontracks, onmove }: Props = $props();

	const item = $derived(row.item);
	const type = $derived(item?.kind === 'random' ? 'random_movie' : 'feature');
	const meta = $derived(itemTypeDisplay(type));
	const Icon = $derived(meta.icon);

	const iconButton =
		'rounded-sm p-1 text-faint hover:bg-surface-3 hover:text-text disabled:opacity-30 ' +
		'disabled:hover:bg-transparent disabled:hover:text-faint';
</script>

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
			{#if item.kind === 'movie'}
				<p class="truncate text-xs text-faint">{trackSummary(item)}</p>
			{:else}
				<p class="truncate text-xs text-faint">Chosen when the playlist is generated</p>
			{/if}
		</div>

		<div class="ml-auto flex shrink-0 items-center gap-1">
			{#if item.kind === 'movie'}
				{#if canChooseTracks(item)}
					<Button size="sm" title="Choose audio and subtitles for {item.title}" onclick={ontracks}>
						Tracks…
					</Button>
				{:else}
					<!-- Tooltip on the wrapper: a disabled button takes no pointer events. -->
					<span title="This movie has one audio track and no subtitles">
						<Button size="sm" disabled>Tracks…</Button>
					</span>
				{/if}
			{/if}
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
				<button
					type="button"
					class={iconButton}
					disabled={row.slotIndex === 0}
					title="Move to the slot above"
					onclick={() => onmove(-1)}
				>
					<ChevronUp size={14} />
				</button>
				<button
					type="button"
					class={iconButton}
					disabled={row.slotIndex === slots - 1}
					title="Move to the slot below"
					onclick={() => onmove(1)}
				>
					<ChevronDown size={14} />
				</button>
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
