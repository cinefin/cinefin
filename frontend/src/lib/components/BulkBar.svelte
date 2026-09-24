<script lang="ts">
	import type { Snippet } from 'svelte';
	import Button from '$lib/components/ui/Button.svelte';

	/** The bulk-action bar shown while a list has a selection. Renders nothing when empty, so
	 *  pages mount it unconditionally. */

	interface Props {
		count: number;
		onclear: () => void;
		children: Snippet;
	}

	let { count, onclear, children }: Props = $props();
</script>

{#if count}
	<div
		class="mb-2 flex flex-wrap items-center gap-2 rounded-md border border-border-strong
			bg-surface-2 px-3 py-2"
	>
		<span class="text-sm font-medium">{count} selected</span>
		{@render children()}
		<Button size="sm" variant="ghost" onclick={onclear}>Clear</Button>
	</div>
{/if}
