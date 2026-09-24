<script lang="ts">
	interface Props {
		value: string;
		options: { value: string; label: string }[];
		placeholder?: string;
		class?: string;
		onchange: (value: string) => void;
	}

	let { value, options, placeholder = '', class: cls = '', onchange }: Props = $props();
</script>

<select
	{value}
	onchange={(e) => onchange((e.target as HTMLSelectElement).value)}
	class="h-8 w-full min-w-0 rounded-md border border-border-strong bg-surface-2 px-2 pr-7 text-sm
		text-text focus:border-accent-dim {cls}"
>
	{#if placeholder}<option value="">{placeholder}</option>{/if}
	{#each options as opt (opt.value)}
		<option value={opt.value}>{opt.label}</option>
	{/each}
</select>
