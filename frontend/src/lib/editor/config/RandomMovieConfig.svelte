<script lang="ts">
	import ConfigField from '../ConfigField.svelte';
	import ConfigForm from '../ConfigForm.svelte';
	import ConfigSelect from '../ConfigSelect.svelte';
	import GenreChips from '../GenreChips.svelte';
	import NumberInput from '../NumberInput.svelte';
	import type { ConfigProps } from '../types';

	let { block, ctx, commit }: ConfigProps = $props();

	type Bound = 'year_from' | 'year_to' | 'runtime_from' | 'runtime_to';
	const set = (field: Bound, value: number | null) => commit(() => (block.content[field] = value));

	function setGenres(ids: number[]): void {
		commit(() => {
			block.content.genre_ids = ids;
			block.content.genre_names = ids.map(
				(id) => ctx.genres.find((g) => g.id === id)?.name ?? String(id)
			);
		});
	}

	const RANGES = [
		{ label: 'Release year', from: 'year_from', to: 'year_to', min: 1900, max: 2030 },
		{ label: 'Runtime (minutes)', from: 'runtime_from', to: 'runtime_to', min: 1, max: 600 }
	] as const;
</script>

<ConfigForm>
	<ConfigField label="Genres" hint="A film must match at least one (any = no genre filter).">
		<GenreChips
			class="min-w-0"
			selected={block.content.genre_ids ?? []}
			genres={ctx.genres}
			onchange={setGenres}
		/>
	</ConfigField>
	<ConfigField label="Rating">
		<ConfigSelect
			value={block.content.certification || ''}
			options={ctx.certifications.map((c) => ({ value: c, label: c }))}
			placeholder="Any"
			onchange={(v) => commit(() => (block.content.certification = v || null))}
		/>
	</ConfigField>
	{#each RANGES as r (r.from)}
		<ConfigField label={r.label}>
			<NumberInput
				value={block.content[r.from]}
				min={r.min}
				max={r.max}
				placeholder="From"
				onchange={(v) => set(r.from, v)}
			/>
			<span class="text-faint" aria-hidden="true">-</span>
			<NumberInput
				value={block.content[r.to]}
				min={r.min}
				max={r.max}
				placeholder="To"
				onchange={(v) => set(r.to, v)}
			/>
		</ConfigField>
	{/each}
</ConfigForm>
