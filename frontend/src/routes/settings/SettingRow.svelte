<script lang="ts">
	// One line of a settings list, in three aligned columns: the setting's name (with an optional
	// hint under it), what it is set to, and on the right a control, an action (›) or ⌄ to open its
	// fields in place, under the value. Rows sit in a SettingList.
	import type { Snippet } from 'svelte';
	import { ChevronDown, ChevronRight } from '@lucide/svelte';

	interface Props {
		label: string;
		/** A short line under the name: when it applies, what it is for. */
		hint?: string;
		summary?: string;
		/** Summary in the mono face (addresses, paths). */
		mono?: boolean;
		/** Inline control in the right column (a switch, buttons). */
		control?: Snippet;
		/** Fields opened under the row. Kept mounted while closed. */
		children?: Snippet;
		open?: boolean;
		/** A row that does something (opens a dialog) instead. */
		onclick?: () => void;
		danger?: boolean;
		labelSnippet?: Snippet;
		summarySnippet?: Snippet;
	}
	let {
		label,
		hint = '',
		summary = '',
		mono = false,
		control,
		children,
		open = $bindable(false),
		onclick,
		danger = false,
		labelSnippet,
		summarySnippet
	}: Props = $props();

	const rowCls =
		'flex min-h-[3.25rem] w-full flex-wrap items-center gap-x-5 gap-y-2 px-4 py-2 text-left text-sm ' +
		'transition-colors sm:grid sm:grid-cols-[13rem_minmax(0,1fr)_auto]';
</script>

{#snippet text()}
	<span class="w-40 shrink-0 sm:w-auto">
		<span class="flex items-center gap-2.5 {danger ? 'text-danger' : ''}">
			{#if labelSnippet}{@render labelSnippet()}{:else}{label}{/if}
		</span>
		{#if hint}<span class="mt-0.5 block text-xs text-faint">{hint}</span>{/if}
	</span>
	<span
		class="min-w-0 flex-1 truncate text-muted {mono ? 'font-mono text-xs' : 'text-[0.8125rem]'}"
	>
		{#if summarySnippet}{@render summarySnippet()}{:else}{summary}{/if}
	</span>
{/snippet}

<div class="border-t border-border first:border-t-0">
	{#if children}
		<button
			type="button"
			class="{rowCls} hover:bg-surface-2/50 {open ? 'bg-surface-2/40' : ''}"
			aria-expanded={open}
			onclick={() => (open = !open)}
		>
			{@render text()}
			<ChevronDown
				size={15}
				class="ml-auto shrink-0 text-faint transition-transform {open ? 'rotate-180' : ''}"
			/>
		</button>
		<div
			class="border-t border-border bg-surface-2/40 px-4 py-4 sm:pr-4 sm:pl-[calc(13rem+2.25rem)]"
			hidden={!open}
		>
			{@render children()}
		</div>
	{:else if onclick}
		<button type="button" class="{rowCls} hover:bg-surface-2/50" {onclick}>
			{@render text()}
			<ChevronRight size={15} class="ml-auto shrink-0 text-faint" />
		</button>
	{:else}
		<div class={rowCls}>
			{@render text()}
			{#if control}<span class="ml-auto flex shrink-0 flex-wrap items-center justify-end gap-1.5"
					>{@render control()}</span
				>{/if}
		</div>
	{/if}
</div>
