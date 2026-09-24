<script lang="ts" module>
	import type { Component } from 'svelte';
	import type { IconProps } from '@lucide/svelte';

	export type MenuItem =
		| { separator: true }
		| {
				label: string;
				icon?: Component<IconProps>;
				onclick: () => void;
				danger?: boolean;
				disabled?: boolean;
				separator?: false;
		  };
</script>

<script lang="ts">
	/**
	 * Menu — a button that opens a small popover of actions (spec §06: 2px
	 * corners, quiet fills, a surface rung on hover; no movement). Closes on
	 * outside click, Escape, or choosing an item. Used on its own ("More ▾") and
	 * as the caret half of a split button (`caretOnly`, attached to a primary).
	 */
	import { ChevronDown } from '@lucide/svelte';

	interface Props {
		items: MenuItem[];
		/** Trigger label; omit with `caretOnly` for the split-button caret. */
		label?: string;
		icon?: Component<IconProps>;
		variant?: 'primary' | 'default' | 'ghost' | 'danger';
		size?: 'sm' | 'md';
		/** Which edge the popover aligns to. */
		align?: 'left' | 'right';
		disabled?: boolean;
		/** Caret-only trigger (for a split button). Needs `ariaLabel`. */
		caretOnly?: boolean;
		ariaLabel?: string;
		/** Extra classes on the trigger (e.g. to attach it to a primary button). */
		class?: string;
	}

	let {
		items,
		label,
		icon: Icon,
		variant = 'default',
		size = 'md',
		align = 'left',
		disabled = false,
		caretOnly = false,
		ariaLabel,
		class: cls = ''
	}: Props = $props();

	let open = $state(false);
	let root = $state<HTMLDivElement>();

	function onWindowClick(e: MouseEvent) {
		if (open && root && !root.contains(e.target as Node)) open = false;
	}
	function onKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape' && open) {
			open = false;
			root?.querySelector<HTMLButtonElement>('[data-menu-trigger]')?.focus();
		}
	}

	function choose(item: Extract<MenuItem, { label: string }>) {
		if (item.disabled) return;
		open = false;
		item.onclick();
	}

	const base =
		'inline-flex items-center justify-center gap-1.5 rounded-md font-medium select-none ' +
		'transition-colors active:brightness-90 disabled:opacity-45 disabled:pointer-events-none whitespace-nowrap';
	const sizes: Record<string, string> = {
		sm: 'h-7 px-2.5 text-xs',
		md: 'h-8 px-3.5 text-[0.84375rem]'
	};
	const variants: Record<string, string> = {
		primary: 'bg-accent text-on-accent hover:bg-accent-hover',
		default:
			'bg-surface-2 text-text border border-border-strong hover:bg-surface-3 active:bg-shell active:brightness-100',
		ghost: 'text-muted hover:text-text hover:bg-surface-2',
		danger:
			'bg-transparent text-danger border border-border-strong hover:bg-danger/10 hover:border-danger/60'
	};
	const caretPad = $derived(caretOnly ? (size === 'sm' ? 'px-1.5' : 'px-2') : '');
	const triggerCls = $derived(`${base} ${sizes[size]} ${variants[variant]} ${caretPad} ${cls}`);
</script>

<svelte:window onclick={onWindowClick} onkeydown={onKeydown} />

<div class="relative inline-flex" bind:this={root}>
	<button
		type="button"
		data-menu-trigger
		class={triggerCls}
		{disabled}
		aria-haspopup="menu"
		aria-expanded={open}
		aria-label={caretOnly ? ariaLabel : undefined}
		onclick={() => (open = !open)}
	>
		{#if Icon}<Icon size={size === 'sm' ? 13 : 14} />{/if}
		{#if label}<span>{label}</span>{/if}
		<ChevronDown
			size={size === 'sm' ? 13 : 14}
			class="transition-transform {open ? 'rotate-180' : ''}"
		/>
	</button>

	{#if open}
		<div
			role="menu"
			class="absolute top-full z-30 mt-1 min-w-44 overflow-hidden rounded-md border border-border-strong bg-surface-1 py-1 shadow-lg shadow-black/30
				{align === 'right' ? 'right-0' : 'left-0'}"
		>
			{#each items as item, i (i)}
				{#if 'separator' in item && item.separator}
					<div class="my-1 h-px bg-border" role="separator"></div>
				{:else if 'label' in item}
					{@const it = item}
					<button
						type="button"
						role="menuitem"
						disabled={it.disabled}
						class="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[0.84375rem] transition-colors
							disabled:opacity-45
							{it.danger ? 'text-danger hover:bg-danger/10' : 'text-text hover:bg-surface-2'}"
						onclick={() => choose(it)}
					>
						{#if it.icon}
							{@const ItemIcon = it.icon}
							<ItemIcon size={14} class="shrink-0 {it.danger ? '' : 'text-muted'}" />
						{/if}
						<span class="min-w-0 flex-1 truncate">{it.label}</span>
					</button>
				{/if}
			{/each}
		</div>
	{/if}
</div>
