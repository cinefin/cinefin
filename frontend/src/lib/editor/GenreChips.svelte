<script lang="ts">
	import type { Snippet } from 'svelte';
	import { X } from '@lucide/svelte';
	import ConfigSelect from './ConfigSelect.svelte';
	import { idOptions, type Option } from './types';

	interface Props {
		selected: number[];
		genres: Option[];
		onchange: (ids: number[]) => void;
		class?: string;
		children?: Snippet;
	}

	let { selected, genres, onchange, class: cls = '', children }: Props = $props();

	const genreName = (id: number) => genres.find((g) => g.id === id)?.name ?? String(id);
	const addable = $derived(genres.filter((g) => !selected.includes(g.id)));
</script>

<div class="flex flex-wrap items-center gap-1.5 {cls}">
	{#if !selected.length}
		<span class="text-xs text-faint">Any genre</span>
	{:else}
		{#each selected as id (id)}
			<span
				class="inline-flex items-center gap-1 rounded-sm bg-accent/15 px-1.5 py-0.5 text-xs text-accent transition-colors"
			>
				{genreName(id)}
				<button
					type="button"
					aria-label="Remove genre"
					onclick={() => onchange(selected.filter((x) => x !== id))}
				>
					<X size={11} />
				</button>
			</span>
		{/each}
	{/if}
	{#if addable.length}
		<ConfigSelect
			value=""
			class="!h-7 !w-auto !pr-6 text-xs"
			options={idOptions(addable)}
			placeholder="+ add"
			onnumber={(v) => v && !selected.includes(v) && onchange([...selected, v])}
		/>
	{/if}
	{@render children?.()}
</div>
