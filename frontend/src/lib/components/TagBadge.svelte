<script lang="ts">
	import type { Snippet } from 'svelte';
	import Badge from '$lib/components/ui/Badge.svelte';

	/**
	 * A user-media tag badge. When the tag carries a colour it tints the chip
	 * with that hue (a faint fill + the colour as text, matching the quiet-tint
	 * badge look); with no colour it falls back to the neutral outline badge.
	 */
	interface Props {
		color?: string | null;
		class?: string;
		children: Snippet;
	}

	let { color = null, class: cls = '', children }: Props = $props();

	// A 6-digit hex + "22" alpha (~13%) gives the same soft-tint fill the token
	// badges use, and the solid hue reads as the text/border.
	const tinted = $derived(!!color && /^#[0-9a-fA-F]{6}$/.test(color));
</script>

{#if tinted}
	<span
		class="inline-flex items-center gap-1 rounded-sm border px-1.5 py-px text-xs font-medium whitespace-nowrap {cls}"
		style="color: {color}; border-color: {color}66; background-color: {color}1f;"
	>
		{@render children()}
	</span>
{:else}
	<Badge variant="outline" class={cls}>{@render children()}</Badge>
{/if}
