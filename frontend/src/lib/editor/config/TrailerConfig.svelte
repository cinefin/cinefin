<script lang="ts">
	import { ArrowLeftRight, Clapperboard } from '@lucide/svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import ConfigField from '../ConfigField.svelte';
	import ConfigForm from '../ConfigForm.svelte';
	import { pickTrailerIntoBlock } from '../pick-actions';
	import type { EditorBlock, EditorContext } from '../types';

	interface Props {
		block: EditorBlock;
		ctx: EditorContext;
		commit: (mutate: () => void) => void;
	}

	let { block, ctx, commit }: Props = $props();

	async function chooseTrailer(): Promise<void> {
		await pickTrailerIntoBlock(block, ctx, commit);
	}
</script>

<ConfigForm>
	<ConfigField label="Trailer" wide>
		{#if block.content.trailer_id}
			<span class="min-w-0 truncate text-sm" title={block.content.title || ''}>
				{block.content.title || 'Trailer'}
			</span>
			<Button size="sm" class="shrink-0" onclick={() => void chooseTrailer()}>
				<ArrowLeftRight size={12} /> Change
			</Button>
		{:else}
			<Button size="sm" onclick={() => void chooseTrailer()}>
				<Clapperboard size={12} /> Choose trailer…
			</Button>
		{/if}
	</ConfigField>
</ConfigForm>
