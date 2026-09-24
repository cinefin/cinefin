<script lang="ts">
	/**
	 * Indeterminate loading — the channel chase on the mark (spec M2/M4).
	 * The wrapper appears only after 250ms of waiting, so a fast response
	 * never flashes it. Determinate work gets a meter, never this.
	 */
	import ChaseMark from '$lib/components/ChaseMark.svelte';

	interface Props {
		/** Loading line shown under the mark. */
		label?: string;
		size?: 'sm' | 'md';
		class?: string;
	}

	let { label, size = 'md', class: cls = '' }: Props = $props();

	const h = $derived(size === 'sm' ? 20 : 28);
</script>

<div
	class="chase-wrap flex flex-col items-center justify-center gap-2.5 py-6 text-muted {cls}"
	role="status"
>
	<ChaseMark height={h} />
	{#if label}<span class="text-sm">{label}</span>{/if}
	<span class="sr-only">Loading</span>
</div>

<style>
	/* Anti-flash: nothing visible for the first 250ms. */
	.chase-wrap {
		opacity: 0;
		animation: appear 0s linear 0.25s both;
	}
	@keyframes appear {
		to {
			opacity: 1;
		}
	}
</style>
