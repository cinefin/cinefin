<script lang="ts">
	import { ArrowLeftRight, Images, X } from '@lucide/svelte';
	import Button from '$lib/components/ui/Button.svelte';
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

	const featureOptions = $derived(
		ctx.mode === 'template'
			? Array.from({ length: Math.max(ctx.featureCount, 0) }, (_, i) => ({
					value: String(i + 1),
					label: `Feature ${i + 1}`
				}))
			: ctx.programmeMovies.map((m, i) => ({
					value: String(m.id),
					label: `Feature ${i + 1} (${m.title})`
				}))
	);

	const selectedValue = $derived(
		ctx.mode === 'template'
			? block.content.bound_to_feature
				? String(block.content.bound_to_feature)
				: ''
			: block.content.reference_movie_id
				? String(block.content.reference_movie_id)
				: ''
	);

	function chooseFeature(v: string): void {
		commit(() => {
			if (ctx.mode === 'template') {
				block.content.bound_to_feature = v === '' ? null : parseInt(v, 10);
			} else {
				block.content.reference_movie_id = v === '' ? null : parseInt(v, 10);
			}
		});
	}

	async function pickOverride(): Promise<void> {
		const picked = await ctx.pickBumper();
		if (!picked) return;
		commit(() => {
			block.content.bumper_id = picked.id;
			block.content.bumper_title = picked.title;
		});
	}

	function clearOverride(): void {
		commit(() => {
			block.content.bumper_id = null;
			block.content.bumper_title = null;
		});
	}
</script>

<ConfigForm>
	<ConfigField label="For feature">
		<ConfigSelect
			value={selectedValue}
			options={featureOptions}
			placeholder="Choose a feature…"
			onchange={chooseFeature}
		/>
	</ConfigField>

	{#if ctx.mode !== 'template'}
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
		{#if ctx.mode !== 'template'}
			{#if block.content.bumper_id}
				<Button size="sm" onclick={() => void pickOverride()}>
					<ArrowLeftRight size={12} /> Change
				</Button>
				<Button size="sm" onclick={clearOverride}>
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
