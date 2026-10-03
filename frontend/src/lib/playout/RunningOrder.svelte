<script lang="ts">
	// The whole programme as one strip sized by length: the title card as a grey pre-show
	// segment set apart, then each item in its type colour; with `onjump`, a segment jumps there.
	import { formatTime } from '$lib/format';
	import { itemTypeClasses, itemTypeLabel } from '$lib/item-types';
	import { can, type PlayoutStatus } from '$lib/playout/phase';
	import type { PlayoutPlaylistItem } from '$lib/stores/player.svelte';

	interface Props {
		status: PlayoutStatus;
		items: PlayoutPlaylistItem[];
		onjump?: (index: number) => void;
		class?: string;
	}
	let { status, items, onjump, class: cls = '' }: Props = $props();

	// Width by length; these ratios stand in where a length is unknown.
	const TYPE_RATIO: Record<string, number> = {
		command: 0.25,
		certification: 0.25,
		title: 0.25,
		bumper: 0.5,
		trailer: 1,
		movie: 3
	};
	const TITLE_SECONDS = 15;

	const offset = $derived(status.playlist?.offset ?? 0);
	const at = $derived(status.playlist?.mpv_position ?? null);
	const jumpable = $derived(!!onjump && can(status, 'jump'));

	const segments = $derived.by(() => {
		const shown = items.filter(
			(it) =>
				(it.programme_position != null && it.type !== 'system') ||
				(it.programme_position == null && it.index > 0 && it.index < offset)
		);
		const length = (it: PlayoutPlaylistItem) =>
			it.programme_position == null ? TITLE_SECONDS : it.duration || 0;
		const known = shown.every((it) => length(it) > 0);
		const size = (it: PlayoutPlaylistItem) =>
			known ? length(it) : (TYPE_RATIO[it.programme_position == null ? 'title' : it.type] ?? 1);
		const total = shown.reduce((sum, it) => sum + size(it), 0) || 1;
		return shown.map((it) => {
			const type = it.programme_position == null ? 'title' : it.type;
			const title = it.programme_position == null ? 'Title card' : it.title;
			const current = it.index === at;
			return {
				index: it.index,
				preshow: it.programme_position == null,
				width: (size(it) / total) * 100,
				bar: itemTypeClasses(type).bar,
				current,
				progress: current ? (status.playback?.percentage ?? 0) : 0,
				label: `${itemTypeLabel(type)} · ${title}${it.duration ? ` · ${formatTime(it.duration)}` : ''}`
			};
		});
	});
</script>

<div class="flex h-1.5 min-w-0 gap-px bg-surface-3 {cls}">
	{#each segments as seg (seg.index)}
		<button
			type="button"
			class="relative h-full {seg.bar} {seg.current
				? ''
				: 'opacity-55'} transition-opacity enabled:hover:opacity-100 disabled:cursor-default"
			style="width: {seg.width.toFixed(3)}%"
			title={jumpable ? `Jump to ${seg.label}` : seg.label}
			aria-label={jumpable ? `Jump to ${seg.label}` : seg.label}
			disabled={!jumpable}
			onclick={() => onjump?.(seg.index)}
		>
			{#if seg.current}
				<span class="absolute inset-y-0 left-0 bg-text/40" style="width: {seg.progress.toFixed(1)}%"
				></span>
			{/if}
		</button>
		{#if seg.preshow}
			<!-- The pre-show stands a little apart from the programme proper. -->
			<span class="w-1 flex-none bg-surface-1" aria-hidden="true"></span>
		{/if}
	{/each}
</div>
