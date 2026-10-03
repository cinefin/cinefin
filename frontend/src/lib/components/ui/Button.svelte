<script lang="ts">
	import type { Snippet } from 'svelte';
	import { buttonClasses, type ButtonSize, type ButtonVariant } from './button-classes';

	interface Props {
		variant?: ButtonVariant;
		size?: ButtonSize;
		type?: 'button' | 'submit';
		disabled?: boolean;
		/** Renders an <a> styled as a button instead. */
		href?: string;
		title?: string;
		onclick?: (event: MouseEvent) => void;
		class?: string;
		children: Snippet;
	}

	let {
		variant = 'default',
		size = 'md',
		type = 'button',
		disabled = false,
		href,
		title,
		onclick,
		class: cls = '',
		children
	}: Props = $props();

	const classes = $derived(`${buttonClasses(variant, size)} ${cls}`);
	// Anchors don't match :disabled, so the <a> branch gets the treatment explicitly.
	const anchorDisabled = $derived(disabled ? 'opacity-45 pointer-events-none' : '');
</script>

{#if href}
	<a
		{href}
		{title}
		{onclick}
		class="{classes} {anchorDisabled}"
		aria-disabled={disabled || undefined}
		tabindex={disabled ? -1 : undefined}
	>
		{@render children()}
	</a>
{:else}
	<button {type} {title} {disabled} {onclick} class={classes}>
		{@render children()}
	</button>
{/if}
