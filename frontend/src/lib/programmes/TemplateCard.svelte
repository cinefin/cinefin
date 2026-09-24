<script lang="ts">
	import { Check } from '@lucide/svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import {
		movieCount,
		templateBreakdown,
		type TemplateSummary
	} from '$lib/programmes/create-types';

	interface Props {
		template: TemplateSummary;
		selected: boolean;
		/** Its feature count doesn't match the chosen films — not buildable. */
		disabled?: boolean;
		note?: string;
		onselect: () => void;
	}

	let { template, selected, disabled = false, note, onselect }: Props = $props();

	const breakdown = $derived(templateBreakdown(template));
</script>

<button
	type="button"
	{disabled}
	class="flex min-w-0 flex-col gap-1.5 border bg-surface-2 p-3 text-left transition-colors
		{selected
		? 'border-accent'
		: disabled
			? 'border-border opacity-45'
			: 'border-border hover:border-border-strong'}"
	aria-pressed={selected}
	onclick={onselect}
>
	<span class="flex w-full items-start gap-2">
		<span class="min-w-0 flex-1 truncate text-sm font-semibold">{template.name}</span>
		{#if selected}
			<Badge variant="accent"><Check size={11} /> Selected</Badge>
		{/if}
		<Badge variant="outline">{movieCount(template.number_of_features)}</Badge>
	</span>
	{#if template.description}
		<span class="line-clamp-2 text-xs text-muted">{template.description}</span>
	{/if}
	<span class="text-xs text-faint">{breakdown}</span>
	{#if note}
		<span class="text-xs {disabled ? 'text-warning' : 'text-muted'}">{note}</span>
	{/if}
</button>
