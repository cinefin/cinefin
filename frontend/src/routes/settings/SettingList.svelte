<script lang="ts">
	// A titled list of SettingRows, like Playout's "Player" and "Global".
	import type { Snippet } from 'svelte';

	interface Props {
		title: string;
		/** One line beside the title: what the list covers. */
		text?: string;
		/** Buttons at the right of the title (Add a player, Sync now). */
		actions?: Snippet;
		children: Snippet;
	}
	let { title, text = '', actions, children }: Props = $props();
</script>

<section>
	<div class="mb-2 flex min-h-8 flex-wrap items-baseline gap-x-2.5 gap-y-1">
		<h2 class="text-[0.8125rem] font-semibold">{title}</h2>
		{#if text}<span class="text-xs text-faint">{text}</span>{/if}
		{#if actions}<div class="ml-auto flex items-center gap-2 self-center">
				{@render actions()}
			</div>{/if}
	</div>
	<div class="border border-border bg-surface-1">{@render children()}</div>
</section>
