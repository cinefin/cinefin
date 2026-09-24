<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		children: Snippet;
		actions?: Snippet;
		class?: string;
	}

	let { children, actions, class: cls = '' }: Props = $props();
</script>

<div class="max-w-2xl {cls}">
	<div class="grid gap-x-4 gap-y-3 sm:grid-cols-2">
		{@render children()}
	</div>
	{#if actions}
		<div class="mt-3 flex flex-wrap items-center gap-2">
			{@render actions()}
		</div>
	{/if}
</div>
