<script lang="ts">
	import type { Component } from 'svelte';
	import type { LucideIcon } from '@lucide/svelte';

	interface Props {
		label: string;
		value: string | number;
		note?: string;
		icon?: LucideIcon;
		tone?: 'neutral' | 'success' | 'warning' | 'danger';
		href?: string;
		class?: string;
	}
	let { label, value, note, icon: Icon, tone = 'neutral', href, class: cls = '' }: Props = $props();

	const TONE: Record<string, string> = {
		neutral: 'text-text',
		success: 'text-success',
		warning: 'text-warning',
		danger: 'text-danger'
	};
</script>

<svelte:element
	this={href ? 'a' : 'div'}
	{href}
	class="block border border-border bg-surface-1 px-3 py-2.5 {href
		? 'hover:border-border-strong'
		: ''} {cls}"
>
	<div class="flex items-baseline gap-2">
		<span class="font-mono text-xl leading-none {TONE[tone]}">{value}</span>
		{#if Icon}
			<span class="ml-auto text-faint"><Icon size={14} /></span>
		{/if}
	</div>
	<div class="mt-1.5 truncate text-xs text-muted">{label}</div>
	<!-- Always rendered, so labels line up across the strip. -->
	<div class="truncate text-[0.65rem] text-faint">{note ?? '\u00a0'}</div>
</svelte:element>
