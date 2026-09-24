<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		/** Card header title; omit for a chromeless body-only card. */
		title?: string;
		/** Optional header extras (badges, buttons), right-aligned. */
		actions?: Snippet;
		/**
		 * The panel that matters on this page — it sits one step further up
		 * the ladder of light (surface-2), so the eye lands there first
		 * without a heading, a colour or a border doing the shouting. At most
		 * one per page: light means "look here", and two of them means
		 * neither does.
		 */
		lifted?: boolean;
		class?: string;
		children: Snippet;
	}

	let { title, actions, lifted = false, class: cls = '', children }: Props = $props();
</script>

<section class="border border-border {lifted ? 'bg-surface-2' : 'bg-surface-1'} {cls}">
	{#if title || actions}
		<!-- Spec §06 .card > header: the title is a quiet label (muted, 12.5px/500); the panel's
		     content carries the weight. -->
		<header class="flex items-center justify-between gap-3 border-b border-border px-3.5 py-2.5">
			{#if title}
				<h2 class="text-[0.78125rem] font-medium text-muted">{title}</h2>
			{/if}
			{#if actions}
				<div class="flex items-center gap-2">{@render actions()}</div>
			{/if}
		</header>
	{/if}
	<div class="p-4">
		{@render children()}
	</div>
</section>
