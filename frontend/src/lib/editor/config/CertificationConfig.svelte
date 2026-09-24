<script lang="ts">
	import ConfigField from '../ConfigField.svelte';
	import ConfigForm from '../ConfigForm.svelte';
	import ConfigSelect from '../ConfigSelect.svelte';
	import type { EditorBlock, EditorContext } from '../types';

	interface Props {
		block: EditorBlock;
		ctx: EditorContext;
		commit: (mutate: () => void) => void;
	}

	let { block, ctx, commit }: Props = $props();

	const movieOptions = $derived.by(() => {
		const options = ctx.programmeMovies.map((m) => ({ value: String(m.id), label: m.title }));
		// A card saved earlier can point at a film since dropped from the rundown;
		// keep it selectable and say so rather than reading as never configured.
		const ref = block.content.reference_movie_id;
		if (ref && !ctx.programmeMovies.some((m) => m.id === ref)) {
			const known = ctx.movies.find((m) => m.id === ref);
			options.push({
				value: String(ref),
				label: `${known?.title ?? `Movie ${ref}`} (no longer in this programme)`
			});
		}
		return options;
	});
	const featureOptions = $derived(
		Array.from({ length: ctx.featureCount }, (_, i) => ({
			value: String(i + 1),
			label: `Feature ${i + 1}`
		}))
	);
</script>

<ConfigForm>
	{#if ctx.mode === 'programme'}
		<ConfigField label="Rating card for">
			<ConfigSelect
				value={block.content.reference_movie_id ? String(block.content.reference_movie_id) : ''}
				options={movieOptions}
				placeholder={ctx.programmeMovies.length
					? 'Select a movie...'
					: 'Add a movie to this programme first'}
				onchange={(v) =>
					commit(() => {
						block.content.reference_movie_id = v === '' ? null : parseInt(v, 10);
					})}
			/>
		</ConfigField>
	{:else}
		<ConfigField label="Rating card for">
			<ConfigSelect
				value={block.content.certification_feature
					? String(block.content.certification_feature)
					: ''}
				options={featureOptions}
				placeholder="Select a feature..."
				onchange={(v) =>
					commit(() => {
						block.content.certification_feature = v === '' ? null : parseInt(v, 10);
					})}
			/>
		</ConfigField>
	{/if}
</ConfigForm>
