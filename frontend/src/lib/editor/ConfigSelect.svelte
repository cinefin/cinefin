<script lang="ts">
	interface Props {
		value: string | number | null | undefined;
		options: { value: string; label: string }[];
		placeholder?: string;
		class?: string;
		onchange?: (value: string) => void;
		/** Numeric variant: '' → null, else the parsed integer. */
		onnumber?: (value: number | null) => void;
	}

	let { value, options, placeholder = '', class: cls = '', onchange, onnumber }: Props = $props();

	function handle(e: Event): void {
		const v = (e.target as HTMLSelectElement).value;
		onchange?.(v);
		onnumber?.(v === '' ? null : parseInt(v, 10));
	}
</script>

<select
	value={String(value ?? '')}
	onchange={handle}
	class="h-8 w-full min-w-0 rounded-md border border-border-strong bg-surface-2 px-2 pr-7 text-sm
		text-text focus:border-accent-dim {cls}"
>
	{#if placeholder}<option value="">{placeholder}</option>{/if}
	{#each options as opt (opt.value)}
		<option value={opt.value}>{opt.label}</option>
	{/each}
</select>
