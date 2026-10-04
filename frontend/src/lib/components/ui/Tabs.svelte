<script lang="ts">
	/** The one tab strip (spec §06 C3), for sections of one thing; roving tabindex + arrow keys. */
	interface Tab {
		id: string;
		label: string;
		count?: number;
	}

	interface Props {
		tabs: Tab[];
		value: string;
		onselect: (id: string) => void;
		/** Accessible name for the tab list. */
		label: string;
		/** id of the panel a tab controls, when the host renders role="tabpanel" regions. */
		panelId?: (id: string) => string;
		class?: string;
	}

	let { tabs, value, onselect, label, panelId, class: cls = '' }: Props = $props();

	let strip = $state<HTMLDivElement | undefined>();

	function focusTab(index: number) {
		const tab = tabs[(index + tabs.length) % tabs.length];
		onselect(tab.id);
		// The button re-renders with the new tabindex; move focus after that.
		queueMicrotask(() =>
			strip?.querySelector<HTMLButtonElement>(`[data-tab="${tab.id}"]`)?.focus()
		);
	}

	function onkeydown(event: KeyboardEvent) {
		const current = tabs.findIndex((t) => t.id === value);
		const to: Record<string, number> = {
			ArrowRight: current + 1,
			ArrowDown: current + 1,
			ArrowLeft: current - 1,
			ArrowUp: current - 1,
			Home: 0,
			End: tabs.length - 1
		};
		if (event.key in to) {
			event.preventDefault();
			focusTab(to[event.key]);
		}
	}
</script>

<!-- The underline (::after): inset 10px, on the strip's hairline, drawn in from the centre. The
     hairline is an inset line inside the strip (not a border) and tabs stand 1px above it, so a
     strip that scrolls sideways on a phone can't clip the underline and a hovered tab can't hide it. -->
<div
	bind:this={strip}
	role="tablist"
	aria-label={label}
	class="flex gap-1 overflow-x-auto shadow-[inset_0_-1px_0_var(--color-border)] {cls}"
>
	{#each tabs as tab (tab.id)}
		{@const active = tab.id === value}
		<button
			type="button"
			role="tab"
			id="tab-{tab.id}"
			data-tab={tab.id}
			aria-selected={active}
			aria-controls={panelId?.(tab.id)}
			tabindex={active ? 0 : -1}
			class="relative mb-px shrink-0 rounded-t-sm px-3.5 pt-2 pb-2.5 text-[0.84375rem] font-medium
				whitespace-nowrap transition-colors duration-[var(--duration-ui)] ease-[var(--ease-panel)]
				after:absolute after:inset-x-[10px] after:-bottom-px after:h-[2px] after:scale-x-0 after:bg-accent
				after:transition-transform after:duration-[var(--duration-ui)] after:ease-[var(--ease-panel)]
				hover:bg-surface-1 hover:text-text aria-selected:after:scale-x-100
				{active ? 'text-text' : 'text-muted'}"
			{onkeydown}
			onclick={() => onselect(tab.id)}
		>
			{tab.label}
			{#if tab.count != null}
				<span class="ml-1 font-mono text-[0.7rem] text-faint">{tab.count}</span>
			{/if}
		</button>
	{/each}
</div>
