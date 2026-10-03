<script lang="ts">
	import { itemTypeDisplay, CUE_LABEL } from '$lib/item-types';
	import Badge from '$lib/components/ui/Badge.svelte';
	import TypeBadge from '$lib/components/TypeBadge.svelte';
	import { rowCols, rowRuntime, type SupportRow } from '$lib/programmes/create-rundown';

	interface Props {
		row: SupportRow;
	}

	let { row }: Props = $props();

	const meta = $derived(itemTypeDisplay(row.type));
	const Icon = $derived(meta.icon);
</script>

<div
	class="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 pl-3 {meta.classes.edge}"
	class:opacity-50={!row.included}
>
	<span class={rowCols.number}>
		{row.included ? String(row.number).padStart(2, '0') : '-'}
	</span>
	<Icon size={14} class="{rowCols.icon} {meta.classes.icon}" aria-hidden="true" />
	<TypeBadge
		type={row.type}
		short
		col
		label={row.cue ? CUE_LABEL : undefined}
		class="self-center"
	/>

	<div class="flex min-w-40 flex-1 flex-wrap items-baseline gap-x-2">
		<span class="truncate text-sm">{row.title}</span>
		{#if row.note}
			<span class="truncate text-xs text-muted">{row.note}</span>
		{/if}
		{#if !row.included}
			<Badge variant="outline">Not included</Badge>
		{/if}
	</div>

	<span class={rowCols.runtime}>
		{#if row.cue}
			—
		{:else if row.runtime !== null && row.runtime > 0}
			{rowRuntime(row.runtime, row.estimated)}
		{/if}
	</span>
</div>
