<script lang="ts">
	import type { Snippet } from 'svelte';
	import Badge from '$lib/components/ui/Badge.svelte';

	/** A user-media tag badge, tinted with the tag's colour when it has one. */
	interface Props {
		color?: string | null;
		class?: string;
		children: Snippet;
	}

	let { color = null, class: cls = '', children }: Props = $props();

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
