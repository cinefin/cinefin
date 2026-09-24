<script lang="ts">
	import { ChevronRight } from '@lucide/svelte';
	import type { Snippet } from 'svelte';

	interface Props {
		title: string;
		note?: string;
		open?: boolean;
		children: Snippet;
	}

	let { title, note, open = $bindable(false), children }: Props = $props();
</script>

<section class="border border-border bg-surface-1">
	<button
		type="button"
		class="flex w-full items-center gap-2 px-4 py-2.5 text-left hover:bg-surface-2"
		aria-expanded={open}
		onclick={() => (open = !open)}
	>
		<ChevronRight
			size={15}
			class="shrink-0 text-muted transition-transform {open ? 'rotate-90' : ''}"
		/>
		<span class="text-sm font-semibold text-text">{title}</span>
		{#if note}
			<span class="ml-auto font-mono text-xs text-faint">{note}</span>
		{/if}
	</button>
	{#if open}
		<div class="border-t border-border p-4">
			{@render children()}
		</div>
	{/if}
</section>
