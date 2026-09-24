<script lang="ts">
	/**
	 * The add-block palette: a vertical list, one plain button per block
	 * type, carrying the type's icon in its family colour (labels, icons and
	 * colours all come from `$lib/item-types`). It lives in a column beside
	 * the block list, so the buttons are full width and left-aligned.
	 * Clicking adds an unconfigured block to the list (content is chosen
	 * inside the block). Types with a `help` explainer get a "?" beside the
	 * button.
	 */
	import { CircleHelp } from '@lucide/svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import { itemTypeDisplay } from '$lib/item-types';
	import type { PaletteEntry } from './types';

	interface Props {
		types: PaletteEntry[];
		onadd: (type: string) => void;
	}

	let { types, onadd }: Props = $props();
</script>

<div class="flex flex-col gap-1">
	{#each types as t (t.type)}
		{@const meta = itemTypeDisplay(t.type)}
		{@const Icon = meta.icon}
		<div class="flex items-center gap-1">
			<Button
				size="sm"
				class="min-w-0 flex-1 justify-start"
				title={t.desc}
				onclick={() => onadd(t.type)}
			>
				<Icon size={13} class="{meta.classes.icon} shrink-0" aria-hidden="true" />
				<span class="truncate">{meta.label}</span>
			</Button>
			<!-- The help slot is always reserved so every button is the same width. -->
			<span class="w-3.5 shrink-0 text-faint" title={t.help}>
				{#if t.help}
					<CircleHelp
						size={13}
						class="cursor-help"
						aria-label="What is a {meta.label.toLowerCase()}?"
					/>
				{/if}
			</span>
		</div>
	{/each}
</div>
