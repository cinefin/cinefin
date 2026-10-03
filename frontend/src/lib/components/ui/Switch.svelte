<script lang="ts">
	/** An on/off switch for a setting that applies at once (no Save); a form field is `Toggle`. */
	interface Props {
		checked: boolean;
		label: string;
		/** The switch's name when it shows no label (a settings row names it). */
		ariaLabel?: string;
		disabled?: boolean;
		/** Called with the new value; the parent saves it and passes `checked` back. */
		onchange: (checked: boolean) => void;
		class?: string;
	}

	let { checked, label, ariaLabel, disabled = false, onchange, class: cls = '' }: Props = $props();
</script>

<button
	type="button"
	role="switch"
	aria-checked={checked}
	aria-label={ariaLabel}
	{disabled}
	onclick={() => onchange(!checked)}
	class="inline-flex items-center gap-2 text-left disabled:opacity-45 {cls}"
>
	<span
		class="relative inline-block h-4 w-7 flex-none rounded-xs transition-colors {checked
			? 'bg-accent'
			: 'bg-surface-3 ring-1 ring-border-strong ring-inset'}"
	>
		<span
			class="absolute top-0.5 h-3 w-3 rounded-xs bg-white transition-[left] {checked
				? 'left-3.5'
				: 'left-0.5'}"
		></span>
	</span>
	{#if label}<span>{label}</span>{/if}
</button>
