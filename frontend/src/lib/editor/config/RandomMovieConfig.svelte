<script lang="ts">
	import { X } from '@lucide/svelte';
	import ConfigField from '../ConfigField.svelte';
	import ConfigForm from '../ConfigForm.svelte';
	import ConfigSelect from '../ConfigSelect.svelte';
	import NumberInput from '../NumberInput.svelte';
	import type { EditorBlock, EditorContext } from '../types';

	interface Props {
		block: EditorBlock;
		ctx: EditorContext;
		commit: (mutate: () => void) => void;
	}

	let { block, ctx, commit }: Props = $props();

	function setBound(
		field: 'year_from' | 'year_to' | 'runtime_from' | 'runtime_to',
		value: number | null
	): void {
		commit(() => {
			block.content[field] = value;
		});
	}

	const selectedGenreIds = $derived(block.content.genre_ids ?? []);
	const genreName = (id: number) => ctx.genres.find((g) => g.id === id)?.name ?? String(id);
	const addableGenres = $derived(ctx.genres.filter((g) => !selectedGenreIds.includes(g.id)));

	function setGenres(ids: number[]): void {
		commit(() => {
			block.content.genre_ids = ids;
			block.content.genre_names = ids.map(genreName);
		});
	}
	function addGenre(id: number): void {
		if (!selectedGenreIds.includes(id)) setGenres([...selectedGenreIds, id]);
	}
	function removeGenre(id: number): void {
		setGenres(selectedGenreIds.filter((x) => x !== id));
	}

	const chip = 'inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-xs transition-colors';
</script>

<ConfigForm>
	<ConfigField label="Genres" hint="A film must match at least one (any = no genre filter).">
		<div class="flex min-w-0 flex-wrap items-center gap-1.5">
			{#if !selectedGenreIds.length}
				<span class="text-xs text-faint">Any genre</span>
			{:else}
				{#each selectedGenreIds as id (id)}
					<span class="{chip} bg-accent/15 text-accent">
						{genreName(id)}
						<button type="button" aria-label="Remove genre" onclick={() => removeGenre(id)}>
							<X size={11} />
						</button>
					</span>
				{/each}
			{/if}
			{#if addableGenres.length}
				<ConfigSelect
					value=""
					class="!h-7 !w-auto !pr-6 text-xs"
					options={addableGenres.map((g) => ({ value: String(g.id), label: g.name }))}
					placeholder="+ add"
					onchange={(v) => v && addGenre(parseInt(v, 10))}
				/>
			{/if}
		</div>
	</ConfigField>
	<ConfigField label="Rating">
		<ConfigSelect
			value={block.content.certification || ''}
			options={ctx.certifications.map((c) => ({ value: c, label: c }))}
			placeholder="Any"
			onchange={(v) =>
				commit(() => {
					block.content.certification = v || null;
				})}
		/>
	</ConfigField>
	<ConfigField label="Release year">
		<NumberInput
			value={block.content.year_from}
			min={1900}
			max={2030}
			placeholder="From"
			onchange={(v) => setBound('year_from', v)}
		/>
		<span class="text-faint" aria-hidden="true">-</span>
		<NumberInput
			value={block.content.year_to}
			min={1900}
			max={2030}
			placeholder="To"
			onchange={(v) => setBound('year_to', v)}
		/>
	</ConfigField>
	<ConfigField label="Runtime (minutes)">
		<NumberInput
			value={block.content.runtime_from}
			min={1}
			max={600}
			placeholder="From"
			onchange={(v) => setBound('runtime_from', v)}
		/>
		<span class="text-faint" aria-hidden="true">-</span>
		<NumberInput
			value={block.content.runtime_to}
			min={1}
			max={600}
			placeholder="To"
			onchange={(v) => setBound('runtime_to', v)}
		/>
	</ConfigField>
</ConfigForm>
