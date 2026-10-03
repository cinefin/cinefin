<script lang="ts">
	import ConfigField from '../ConfigField.svelte';
	import ConfigForm from '../ConfigForm.svelte';
	import ConfigSelect from '../ConfigSelect.svelte';
	import { featureOptions, type ConfigProps } from '../types';

	let { block, ctx, commit }: ConfigProps = $props();

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
</script>

<ConfigForm>
	<ConfigField label="Rating card for">
		{#if ctx.mode === 'programme'}
			<ConfigSelect
				value={block.content.reference_movie_id}
				options={movieOptions}
				placeholder={ctx.programmeMovies.length
					? 'Select a movie...'
					: 'Add a movie to this programme first'}
				onnumber={(v) => commit(() => (block.content.reference_movie_id = v))}
			/>
		{:else}
			<ConfigSelect
				value={block.content.certification_feature}
				options={featureOptions(ctx.featureCount)}
				placeholder="Select a feature..."
				onnumber={(v) => commit(() => (block.content.certification_feature = v))}
			/>
		{/if}
	</ConfigField>
</ConfigForm>
