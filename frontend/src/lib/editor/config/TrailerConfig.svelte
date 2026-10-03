<script lang="ts">
	import { ArrowLeftRight, Clapperboard } from '@lucide/svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import ConfigField from '../ConfigField.svelte';
	import ConfigForm from '../ConfigForm.svelte';
	import { pickTrailerIntoBlock } from '../pick-actions';
	import type { ConfigProps } from '../types';

	let { block, ctx, commit }: ConfigProps = $props();

	const choose = () => void pickTrailerIntoBlock(block, ctx, commit);
</script>

<ConfigForm>
	<ConfigField label="Trailer" wide>
		{#if block.content.trailer_id}
			<span class="min-w-0 truncate text-sm" title={block.content.title || ''}>
				{block.content.title || 'Trailer'}
			</span>
			<Button size="sm" class="shrink-0" onclick={choose}>
				<ArrowLeftRight size={12} /> Change
			</Button>
		{:else}
			<Button size="sm" onclick={choose}>
				<Clapperboard size={12} /> Choose trailer…
			</Button>
		{/if}
	</ConfigField>
</ConfigForm>
