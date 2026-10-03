<script lang="ts">
	// A programme's features as an overlapping stack; with `currentId` the playing one is lit.
	import { Film } from '@lucide/svelte';

	interface Feature {
		id: number;
		title: string;
		thumbnail_url?: string | null;
	}
	interface Props {
		films: Feature[];
		currentId?: number | null;
		size?: 'sm' | 'md';
		class?: string;
	}
	let { films, currentId = null, size = 'sm', class: cls = '' }: Props = $props();

	const SIZES = {
		sm: { tile: 'w-9', overlap: '-ml-4', icon: 12, max: 3 },
		md: { tile: 'w-16', overlap: '-ml-10', icon: 14, max: 4 }
	};
	const s = $derived(SIZES[size]);
	const at = $derived(films.findIndex((f) => f.id === currentId));
	const start = $derived(Math.max(0, Math.min(at - 1, films.length - s.max)));
	const shown = $derived(films.slice(start, start + s.max));
	const extra = $derived(films.length - shown.length);

	function depth(i: number): number {
		return at < 0 ? i : s.max - Math.abs(start + i - at);
	}
	function tone(i: number): string {
		if (at < 0) return '';
		const idx = start + i;
		return idx === at ? 'border-border-strong' : idx < at ? 'opacity-35' : 'opacity-70';
	}

	const tile = 'relative aspect-[2/3] shrink-0 overflow-hidden border border-border bg-surface-2';
</script>

<div class="relative flex items-center {cls}">
	{#each shown as film, i (film.id)}
		<div
			class="{tile} {s.tile} {i ? s.overlap : ''} transition-opacity {tone(i)}"
			style="z-index: {depth(i)}"
			title={film.title}
		>
			{#if film.thumbnail_url}
				<img src={film.thumbnail_url} alt="" loading="lazy" class="h-full w-full object-cover" />
			{:else}
				<div class="flex h-full items-center justify-center text-faint">
					<Film size={s.icon} />
				</div>
			{/if}
		</div>
	{/each}
	{#if extra}
		<span
			class="absolute right-0 bottom-0 z-10 bg-shell/85 px-1 font-mono text-[0.65rem] text-muted"
			title="{extra} more feature{extra === 1 ? '' : 's'}"
		>
			+{extra}
		</span>
	{/if}
	{#if !films.length}
		<div class="{tile} {s.tile} flex items-center justify-center text-faint" title="No films yet">
			<Film size={s.icon} />
		</div>
	{/if}
</div>
