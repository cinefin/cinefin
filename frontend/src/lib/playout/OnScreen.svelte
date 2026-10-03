<script lang="ts">
	/**
	 * What the audience sees, drawn simply (never live video): the mark on standby, the
	 * programme's name on a title card, black during a hold, else the item's title.
	 */
	import Logo from '$lib/components/shell/Logo.svelte';
	import { preview, type PlayoutStatus } from '$lib/playout/phase';

	interface Props {
		status: PlayoutStatus;
		/** Aspect/size classes; a 16:9 screen by default. */
		class?: string;
	}
	let { status, class: cls = 'aspect-video' }: Props = $props();

	const view = $derived(preview(status));
</script>

<div
	class="relative w-full overflow-hidden border border-border bg-black {cls}"
	role="img"
	aria-label="On screen: {status.screen || 'nothing'}"
>
	{#if view.kind === 'mark'}
		<div class="flex h-full items-center justify-center">
			<Logo markClass="h-9" wordmark />
		</div>
		{#if status.player?.show_status}
			<span class="absolute right-3 bottom-2 text-[0.6rem] text-muted">
				Ready · {status.player.name}
			</span>
		{/if}
	{:else if view.kind === 'title'}
		<div class="flex h-full items-center justify-center px-6">
			<span class="text-center font-display text-2xl leading-tight text-white sm:text-3xl"
				>{view.text}</span
			>
		</div>
	{:else if view.kind === 'item'}
		<span class="absolute bottom-2 left-3 max-w-[90%] truncate text-xs text-muted">
			On screen · {view.text}
		</span>
	{:else if view.kind === 'black'}
		<span class="absolute bottom-2 left-3 text-xs text-faint">Black · {view.text}</span>
	{:else}
		<div class="flex h-full items-center justify-center text-xs text-faint">No picture</div>
	{/if}
</div>
