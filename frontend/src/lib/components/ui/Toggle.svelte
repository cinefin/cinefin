<script lang="ts">
	interface Props {
		label: string;
		checked?: boolean;
		disabled?: boolean;
		dirty?: boolean;
		hint?: string;
		onchange?: (event: Event) => void;
	}

	let {
		label,
		checked = $bindable(false),
		disabled = false,
		dirty = false,
		hint,
		onchange
	}: Props = $props();
</script>

<label class="flex items-start gap-2 text-sm {disabled ? 'opacity-50' : ''}">
	<input type="checkbox" bind:checked {disabled} {onchange} class="cpx-check mt-0.5" />
	<span>
		<span class="flex items-center gap-1.5">
			{label}
			{#if dirty}
				<span class="h-1.5 w-1.5 bg-warning" title="Unsaved change"></span>
			{/if}
		</span>
		{#if hint}
			<span class="mt-0.5 block text-xs text-faint">{hint}</span>
		{/if}
	</span>
</label>

<style>
	.cpx-check {
		appearance: none;
		width: 1rem;
		height: 1rem;
		flex: none;
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-sm);
		background: var(--color-surface-2);
		transition:
			background-color 0.12s ease,
			border-color 0.12s ease;
		cursor: pointer;
	}
	.cpx-check:hover:not(:disabled) {
		border-color: var(--color-faint);
	}
	.cpx-check:checked {
		border-color: var(--color-accent);
		background-color: var(--color-accent);
		background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='20 6 9 17 4 12'/%3E%3C/svg%3E");
		background-repeat: no-repeat;
		background-position: center;
		background-size: 0.7rem;
	}
	.cpx-check:focus-visible {
		outline: 2px solid color-mix(in srgb, var(--color-accent) 60%, transparent);
		outline-offset: 1px;
	}
</style>
