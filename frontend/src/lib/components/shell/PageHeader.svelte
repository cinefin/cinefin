<script lang="ts">
	import { pageHeader, type PageHeaderSpec } from '$lib/stores/pageHeader.svelte';

	let { title, count, back, actions, tone }: PageHeaderSpec = $props();

	$effect(() => {
		const spec = { title, count, back, actions, tone };
		pageHeader.current = spec;
		return () => {
			if (pageHeader.current === spec) pageHeader.current = null;
		};
	});
</script>

<svelte:head><title>{title} - Cinefin</title></svelte:head>

<!-- The topbar carries the actions from lg; below that they lead the page. -->
{#if actions}
	<div class="mb-4 flex flex-wrap items-center gap-2 lg:hidden">{@render actions()}</div>
{/if}
