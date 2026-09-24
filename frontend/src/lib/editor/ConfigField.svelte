<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		label: string;
		wide?: boolean;
		hint?: string | null;
		children: Snippet;
	}

	let { label, wide = false, hint = null, children }: Props = $props();
</script>

<div class="min-w-0 {wide ? 'sm:col-span-2' : ''}">
	<span class="mb-1 block text-xs font-medium text-muted">{label}</span>
	<div class="flex min-h-8 min-w-0 items-center gap-2">
		{@render children()}
	</div>
	{#if hint}
		<p class="mt-1 text-xs text-faint">{hint}</p>
	{/if}
</div>
