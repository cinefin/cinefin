<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		/** Card header title; omit for a chromeless body-only card. */
		title?: string;
		/** Optional header extras (badges, buttons), right-aligned. */
		actions?: Snippet;
		/** The panel that matters on this page (surface-2) — at most one per page. */
		lifted?: boolean;
		class?: string;
		children: Snippet;
	}

	let { title, actions, lifted = false, class: cls = '', children }: Props = $props();
</script>

<section class="border border-border {lifted ? 'bg-surface-2' : 'bg-surface-1'} {cls}">
	{#if title || actions}
		<header class="flex items-center justify-between gap-3 border-b border-border px-3.5 py-2.5">
			{#if title}
				<h2 class="text-[0.78125rem] font-medium text-muted">{title}</h2>
			{/if}
			{#if actions}
				<div class="flex items-center gap-2">{@render actions()}</div>
			{/if}
		</header>
	{/if}
	<div class="min-h-0 flex-1 p-4">
		{@render children()}
	</div>
</section>
