<script lang="ts">
	interface Props {
		value: number | null | undefined;
		min?: number;
		max?: number;
		placeholder?: string;
		class?: string;
		onchange: (value: number | null) => void;
	}

	let { value, min, max, placeholder, class: cls = '', onchange }: Props = $props();

	function handle(e: Event): void {
		const raw = (e.target as HTMLInputElement).value.trim();
		if (raw === '') {
			onchange(null);
			return;
		}
		const parsed = parseInt(raw, 10);
		if (!Number.isNaN(parsed)) onchange(parsed);
	}
</script>

<input
	type="number"
	value={value ?? ''}
	{min}
	{max}
	{placeholder}
	onchange={handle}
	class="h-8 w-full max-w-40 min-w-0 rounded-md border border-border-strong bg-surface-2 px-2 text-sm
		text-text placeholder:text-faint focus:border-accent-dim {cls}"
/>
