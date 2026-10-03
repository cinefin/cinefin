<script lang="ts" module>
	import type { LucideIcon } from '@lucide/svelte';

	export type MenuItem =
		| { separator: true }
		| {
				label: string;
				icon?: LucideIcon;
				onclick: () => void;
				danger?: boolean;
				disabled?: boolean;
				separator?: false;
		  };
</script>

<script lang="ts">
	// A button that opens a small popover of actions; closes on outside click, Escape or a choice.
	// Used on its own ("More ▾") and as the caret half of a split button (`caretOnly`).
	import { ChevronDown } from '@lucide/svelte';
	import { buttonClasses, type ButtonVariant } from './button-classes';

	interface Props {
		items: MenuItem[];
		/** Trigger label; omit with `caretOnly` for the split-button caret. */
		label?: string;
		icon?: LucideIcon;
		variant?: ButtonVariant;
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

	const caretPad = $derived(caretOnly ? (size === 'sm' ? 'px-1.5' : 'px-2') : '');
	const triggerCls = $derived(`${buttonClasses(variant, size)} ${caretPad} ${cls}`);
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
		aria-label={ariaLabel}
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
