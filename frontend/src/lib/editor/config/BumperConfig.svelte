<script lang="ts">
	import { ArrowLeftRight, Images } from '@lucide/svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import ConfigField from '../ConfigField.svelte';
	import ConfigForm from '../ConfigForm.svelte';
	import ConfigSelect from '../ConfigSelect.svelte';
	import NumberInput from '../NumberInput.svelte';
	import { pickBumperIntoBlock } from '../pick-actions';
	import { idOptions, type ConfigProps } from '../types';

	let { block, ctx, commit }: ConfigProps = $props();

	// Can't be a pure $derived of tag_id: switching TO random has no tag yet, so it
	// would snap back to specific and never open. Seed once (BlockList keys per uid).
	// svelte-ignore state_referenced_locally
	let mode = $state<'specific' | 'random'>(block.content.tag_id ? 'random' : 'specific');

	function setMode(next: 'specific' | 'random'): void {
		if (next === mode) return;
		mode = next;
		commit(() => {
			if (next === 'random') {
				block.content.bumper_id = null;
				block.content.title = null;
				block.content.count = block.content.count ?? 1;
			} else {
				block.content.tag_id = null;
				block.content.tag_name = null;
			}
		});
	}

	const chooseBumper = () => void pickBumperIntoBlock(block, ctx, commit);

	const MODES = [
		['specific', 'Specific clip'],
		['random', 'Random from tag']
	] as const;
</script>

<ConfigForm>
	<ConfigField label="Mode" wide>
		<div class="flex w-full max-w-xs gap-1" role="group" aria-label="User media mode">
			{#each MODES as [value, label] (value)}
				<button
					type="button"
					class="h-8 flex-1 rounded-sm border border-border-strong px-3 text-sm text-muted transition-colors hover:text-text {mode ===
					value
						? 'bg-surface-3 text-text'
						: ''}"
					aria-pressed={mode === value}
					onclick={() => setMode(value)}
				>
					{label}
				</button>
			{/each}
		</div>
	</ConfigField>

	{#if mode === 'specific'}
		<ConfigField label="Clip" wide>
			{#if block.content.bumper_id}
				<span class="min-w-0 truncate text-sm" title={block.content.title || ''}>
					{block.content.title || 'User media'}
				</span>
				<Button size="sm" class="shrink-0" onclick={chooseBumper}>
					<ArrowLeftRight size={12} /> Change
				</Button>
			{:else}
				<Button size="sm" onclick={chooseBumper}>
					<Images size={12} /> Choose user media…
				</Button>
			{/if}
		</ConfigField>
	{:else}
		<ConfigField label="Tag">
			<ConfigSelect
				value={block.content.tag_id}
				options={idOptions(ctx.tags)}
				placeholder="Select..."
				onnumber={(v) => {
					const tag = ctx.tags.find((t) => t.id === v);
					if (!tag) return;
					commit(() => {
						block.content.tag_id = tag.id;
						block.content.tag_name = tag.name;
					});
				}}
			/>
		</ConfigField>
		<ConfigField label="How many to play">
			<NumberInput
				value={block.content.count || 1}
				min={1}
				max={10}
				onchange={(v) =>
					commit(() => {
						block.content.count = v ?? 1;
					})}
			/>
		</ConfigField>
	{/if}
</ConfigForm>
