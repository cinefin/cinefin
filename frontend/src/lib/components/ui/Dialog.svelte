<script lang="ts">
	import type { Snippet } from 'svelte';
	import { X } from '@lucide/svelte';

	interface Props {
		/** Two-way: bind:open — the dialog opens/closes to match. */
		open?: boolean;
		title?: string;
		/** Footer content (usually Buttons), right-aligned. */
		footer?: Snippet;
		/**
		 * Width of the dialog. Set this rather than passing a `max-w-*` class:
		 * Tailwind emits `max-w-lg` after the larger sizes, so a class on the
		 * consumer silently loses to the default and the dialog stays narrow.
		 */
		size?: 'md' | 'lg' | 'xl' | '2xl' | '3xl';
		class?: string;
		children: Snippet;
	}

	let {
		open = $bindable(false),
		title,
		footer,
		size = 'lg',
		class: cls = '',
		children
	}: Props = $props();

	// Full class names — Tailwind only emits what it can see in the source.
	const widths: Record<NonNullable<Props['size']>, string> = {
		md: 'max-w-md',
		lg: 'max-w-lg',
		xl: 'max-w-xl',
		'2xl': 'max-w-2xl',
		'3xl': 'max-w-3xl'
	};

	let el: HTMLDialogElement | undefined = $state();

	$effect(() => {
		if (!el) return;
		if (open && !el.open) el.showModal();
		else if (!open && el.open) el.close();
	});
</script>

<dialog
	bind:this={el}
	onclose={() => (open = false)}
	onclick={(e) => {
		// Click on the backdrop (the dialog element itself) closes.
		if (e.target === el) open = false;
	}}
	class="m-auto w-full {widths[size]} border border-border-strong bg-surface-1 p-0
		text-text backdrop:bg-black/60 {cls}"
>
	<div class="flex items-center justify-between border-b border-border px-4 py-3">
		<h2 class="text-sm font-semibold">{title}</h2>
		<button
			type="button"
			class="rounded-sm p-1 text-muted hover:bg-surface-2 hover:text-text"
			aria-label="Close"
			onclick={() => (open = false)}
		>
			<X size={16} />
		</button>
	</div>
	<div class="p-4">
		{@render children()}
	</div>
	{#if footer}
		<div class="flex justify-end gap-2 border-t border-border px-4 py-3">
			{@render footer()}
		</div>
	{/if}
</dialog>
