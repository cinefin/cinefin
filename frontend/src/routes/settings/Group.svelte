<script lang="ts">
	// One part of a settings section, stacked under the one before: a heading, then its fields.
	import type { Snippet } from 'svelte';

	interface Props {
		title: string;
		id?: string;
		text?: string;
		class?: string;
		children: Snippet;
	}
	let { title, id, text, class: cls = '', children }: Props = $props();
</script>

<section {id} class="scroll-mt-20 border-t border-border pt-6 first:border-t-0 first:pt-0 {cls}">
	<h2 class="text-[0.95rem] font-medium">{title}</h2>
	{#if text}<p class="mt-0.5 text-xs text-muted">{text}</p>{/if}
	<div class="mt-4">{@render children()}</div>
</section>
