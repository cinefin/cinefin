<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		value?: string;
		id?: string;
		name?: string;
		disabled?: boolean;
		class?: string;
		onchange?: (event: Event) => void;
		/** <option> elements. */
		children: Snippet;
	}

	let {
		value = $bindable(''),
		id,
		name,
		disabled = false,
		class: cls = '',
		onchange,
		children
	}: Props = $props();
</script>

<select
	{id}
	{name}
	{disabled}
	{onchange}
	bind:value
	class="cpx-select h-9 max-w-xl rounded-md border border-border-strong bg-surface-2 px-2.5 pr-8 text-sm text-text
		transition-colors hover:border-faint
		focus:border-accent focus:ring-1 focus:ring-inset focus:ring-accent/45 focus:outline-none
		disabled:opacity-45 disabled:hover:border-border-strong {cls}"
>
	{@render children()}
</select>

<style>
	/* Own the dropdown arrow: drop the OS-native one (grey, inconsistent per
	   browser/OS) for a chevron that matches the dark, square theme. */
	.cpx-select {
		appearance: none;
		background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%23848b98' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E");
		background-repeat: no-repeat;
		background-position: right 0.55rem center;
		background-size: 14px;
	}
</style>
