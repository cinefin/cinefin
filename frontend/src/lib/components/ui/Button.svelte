<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		variant?: 'primary' | 'default' | 'ghost' | 'danger';
		size?: 'sm' | 'md';
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

	// Quiet buttons: 2px corners (radius token), subtly filled default, no glow.
	const base =
		'inline-flex items-center justify-center gap-1.5 rounded-md font-medium select-none ' +
		'transition-colors active:brightness-90 disabled:opacity-45 disabled:pointer-events-none whitespace-nowrap';
	const sizes: Record<string, string> = {
		sm: 'h-7 px-2.5 text-xs',
		md: 'h-8 px-3.5 text-[0.84375rem]'
	};
	const variants: Record<string, string> = {
		primary: 'bg-accent text-on-accent hover:bg-accent-hover',
		// Spec §06: subtly filled — a rung up on hover, down to the shell when pressed.
		default:
			'bg-surface-2 text-text border border-border-strong hover:bg-surface-3 active:bg-shell active:brightness-100',
		ghost: 'text-muted hover:text-text hover:bg-surface-2',
		danger:
			'bg-transparent text-danger border border-border-strong hover:bg-danger/10 hover:border-danger/60'
	};

	const classes = $derived(`${base} ${sizes[size]} ${variants[variant]} ${cls}`);
	// Anchors don't satisfy the CSS :disabled pseudo-class, so the base
	// disabled: utilities never apply to the <a> branch. Apply the treatment
	// unconditionally and take the link out of the tab order when disabled.
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
