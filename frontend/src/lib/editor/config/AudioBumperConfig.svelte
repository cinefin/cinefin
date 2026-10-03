<script lang="ts">
	import { ArrowLeftRight, Images, X } from '@lucide/svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import ConfigField from '../ConfigField.svelte';
	import ConfigForm from '../ConfigForm.svelte';
	import ConfigSelect from '../ConfigSelect.svelte';
	import { featureOptions, type ConfigProps } from '../types';

	let { block, ctx, commit }: ConfigProps = $props();

	const template = $derived(ctx.mode === 'template');

	function setOverride(picked: { id: number; title: string } | null): void {
		commit(() => {
			block.content.bumper_id = picked?.id ?? null;
			block.content.bumper_title = picked?.title ?? null;
		});
	}

	async function pickOverride(): Promise<void> {
		const picked = await ctx.pickBumper();
		if (picked) setOverride(picked);
	}
</script>

<ConfigForm>
	<ConfigField label="For feature">
		<ConfigSelect
			value={template ? block.content.bound_to_feature : block.content.reference_movie_id}
			options={template
				? featureOptions(ctx.featureCount)
				: ctx.programmeMovies.map((m, i) => ({
						value: String(m.id),
						label: `Feature ${i + 1} (${m.title})`
					}))}
			placeholder="Choose a feature…"
			onnumber={(v) =>
				commit(() => {
					if (template) block.content.bound_to_feature = v;
					else block.content.reference_movie_id = v;
				})}
		/>
	</ConfigField>

	{#if !template}
		<ConfigField label="Clip">
			{#if block.content.bumper_id}
				<span class="truncate text-sm" title={block.content.bumper_title || ''}>
					{block.content.bumper_title || 'User media'}
				</span>
			{:else}
				<span class="text-sm text-muted">Auto - matches the feature's audio format</span>
			{/if}
		</ConfigField>
	{/if}

	{#snippet actions()}
		{#if !template}
			{#if block.content.bumper_id}
				<Button size="sm" onclick={() => void pickOverride()}>
					<ArrowLeftRight size={12} /> Change
				</Button>
				<Button size="sm" onclick={() => setOverride(null)}>
					<X size={12} /> Back to auto
				</Button>
			{:else}
				<Button size="sm" onclick={() => void pickOverride()}>
					<Images size={12} /> Pick a specific clip…
				</Button>
			{/if}
		{/if}
	{/snippet}
</ConfigForm>
