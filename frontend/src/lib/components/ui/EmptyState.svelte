<script lang="ts">
	import type { Component, Snippet } from 'svelte';
	import type { LucideIcon } from '@lucide/svelte';

	interface Props {
		/** A @lucide/svelte icon component, e.g. `icon={Film}`. */
		icon?: LucideIcon;
		title: string;
		message?: string;
		/** Call to action (usually a Button). An empty screen invites action. */
		action?: Snippet;
		compact?: boolean;
		class?: string;
	}

	let { icon: Icon, title, message, action, compact = false, class: cls = '' }: Props = $props();
</script>

<div class="flex flex-col items-center text-center {compact ? 'py-6' : 'py-10'} {cls}">
	{#if Icon}
		<span aria-hidden="true" class="mb-2 text-faint"><Icon size={20} /></span>
	{/if}
	<p class="text-sm font-medium text-text">{title}</p>
	{#if message}
		<p class="mt-1 max-w-sm text-sm text-muted">{message}</p>
	{/if}
	{#if action}
		<div class="mt-3 flex flex-wrap items-center justify-center gap-2">{@render action()}</div>
	{/if}
</div>
