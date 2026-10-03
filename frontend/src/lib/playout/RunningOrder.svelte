<script lang="ts">
	// The whole programme as one strip sized by length, with a floor so short items stay visible: the
	// title card as a grey pre-show segment set apart, then each item in its type colour. Hovering or
	// focusing a segment shows its card; with `onjump`, a segment jumps there.
	import { formatClock, formatTime } from '$lib/format';
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
	// No segment is narrower than this share of the strip, however short.
	const FLOOR = 0.045;
	// rem, so the card follows the density zoom.
	const CARD_REM = 15;

	const offset = $derived(status.playlist?.offset ?? 0);
	const at = $derived(status.playlist?.mpv_position ?? null);
	const jumpable = $derived(!!onjump && can(status, 'jump'));
	let hovered = $state<number | null>(null);

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
		const shares = shown.map((it) => Math.max(size(it) / total, FLOOR));
		const sum = shares.reduce((a, b) => a + b, 0);
		let before = 0;
		return shown.map((it, i) => {
			const width = (shares[i] / sum) * 100;
			const center = before + width / 2;
			before += width;
			const type = it.programme_position == null ? 'title' : it.type;
			const title = it.programme_position == null ? 'Title card' : it.title;
			return {
				index: it.index,
				type,
				title,
				duration: length(it),
				position: it.programme_position,
				preshow: it.programme_position == null,
				width,
				center,
				bar: itemTypeClasses(type).bar,
				label: `${itemTypeLabel(type)} · ${title}${it.duration ? ` · ${formatTime(it.duration)}` : ''}`
			};
		});
	});

	const card = $derived.by(() => {
		const i = segments.findIndex((s) => s.index === hovered);
		if (i < 0) return null;
		const seg = segments[i];
		const cur = segments.findIndex((s) => s.index === at);
		const remaining = status.playback?.remaining ?? 0;
		let state: string;
		let startsIn: number | null = null;
		if (cur < 0) state = '';
		else if (i < cur) state = 'Played';
		else if (i === cur)
			state = `${status.phase === 'playing' ? 'Playing' : 'On screen'} · ${formatTime(remaining)} left`;
		else {
			startsIn = remaining + segments.slice(cur + 1, i).reduce((sum, s) => sum + s.duration, 0);
			state = `${i === cur + 1 ? 'Up next · in' : 'In'} ${formatTime(startsIn)}`;
		}
		return {
			...seg,
			current: i === cur,
			state,
			starts: startsIn != null ? formatClock(new Date(Date.now() + startsIn * 1000)) : null,
			place:
				seg.position == null
					? 'Pre-show'
					: `${seg.position + 1} of ${status.playlist?.total_items ?? segments.length}`
		};
	});
</script>

<!-- The row is the hit area; the visible strip inside it is thinner. -->
<div class="relative min-w-0 {cls}">
	<div
		class="flex h-6 items-center gap-px"
		role="presentation"
		onmouseleave={() => (hovered = null)}
	>
		{#each segments as seg (seg.index)}
			{@const current = seg.index === at}
			{@const played = at != null && seg.index < at}
			<button
				type="button"
				class="flex h-full min-w-0 items-center {jumpable && !current
					? 'cursor-pointer'
					: 'cursor-default'}"
				style="flex: {seg.width.toFixed(3)} 1 0%"
				aria-label={jumpable && !current ? `Jump to ${seg.label}` : seg.label}
				aria-disabled={!jumpable || current}
				onmouseenter={() => (hovered = seg.index)}
				onfocus={() => (hovered = seg.index)}
				onblur={() => (hovered = null)}
				onclick={() => jumpable && !current && onjump?.(seg.index)}
			>
				<span
					class="relative block w-full {seg.bar} h-1.5 transition-opacity {current ||
					hovered === seg.index
						? 'opacity-100'
						: played
							? 'opacity-35'
							: 'opacity-60'}"
				>
					{#if current}
						<span
							class="absolute inset-y-0 left-0 bg-text/40 shadow-[inset_-2px_0_0_var(--color-text)]"
							style="width: {(status.playback?.percentage ?? 0).toFixed(1)}%"
						></span>
					{/if}
				</span>
			</button>
			{#if seg.preshow}
				<!-- The pre-show stands a little apart from the programme proper. -->
				<span class="w-1 flex-none" aria-hidden="true"></span>
			{/if}
		{/each}
	</div>

	{#if card}
		<div
			role="tooltip"
			class="pointer-events-none absolute bottom-[calc(100%+0.375rem)] z-30 border border-border-strong bg-surface-2 p-3 shadow-lg shadow-black/30"
			style="width: {CARD_REM}rem; left: clamp(0rem, calc({card.center.toFixed(2)}% - {CARD_REM /
				2}rem), calc(100% - {CARD_REM}rem))"
		>
			<p class="flex items-center gap-2 font-mono text-[0.6875rem] text-muted">
				<span class="size-2 flex-none {card.bar}"></span>
				{itemTypeLabel(card.type)}
				<span class="ml-auto text-faint">{card.place}</span>
			</p>
			<p class="mt-2 text-sm leading-snug font-semibold">{card.title}</p>
			{#if card.duration || card.starts}
				<dl class="mt-2.5 grid grid-cols-[auto_1fr] gap-x-3.5 gap-y-1 font-mono text-xs">
					{#if card.duration}
						<dt class="text-faint">Length</dt>
						<dd>{formatTime(card.duration)}</dd>
					{/if}
					{#if card.starts}
						<dt class="text-faint">Starts</dt>
						<dd>{card.starts}</dd>
					{/if}
				</dl>
			{/if}
			{#if card.current}
				<div class="mt-2.5 h-0.5 bg-border">
					<div
						class="h-full {card.bar}"
						style="width: {(status.playback?.percentage ?? 0).toFixed(1)}%"
					></div>
				</div>
			{/if}
			{#if card.state}
				<p
					class="mt-2.5 font-mono text-xs {card.current
						? 'text-live'
						: card.state === 'Played'
							? 'text-faint'
							: 'text-muted'}"
				>
					{card.state}
				</p>
			{/if}
			{#if jumpable && !card.current}
				<p class="mt-2.5 border-t border-border pt-2 font-mono text-[0.6875rem] text-faint">
					Click to jump here
				</p>
			{/if}
		</div>
		<span
			class="pointer-events-none absolute bottom-[calc(100%+0.125rem)] z-30 size-2 rotate-45 border-r border-b border-border-strong bg-surface-2"
			style="left: calc({card.center.toFixed(2)}% - 0.25rem)"
			aria-hidden="true"
		></span>
	{/if}
</div>
