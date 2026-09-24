<script lang="ts">
	import { base } from '$app/paths';
	import { Film } from '@lucide/svelte';
	import MoviePanel from '$lib/library/MoviePanel.svelte';
	import type { MovieListItem } from './data.svelte';

	interface Props {
		movies: MovieListItem[];
		onmutated?: () => void;
		variant?: 'grid' | 'shelf';
		captions?: boolean;
		size?: 'sm' | 'md';
		cols?: 6 | 8 | 12;
	}
	let {
		movies,
		onmutated,
		variant = 'grid',
		captions = true,
		size = 'md',
		cols = 6
	}: Props = $props();

	const shelfWidth = $derived(size === 'sm' ? 'w-16 shrink-0 sm:w-20' : 'w-24 shrink-0 sm:w-28');

	// Static class strings — Tailwind cannot see an interpolated column count.
	const GRID: Record<number, string> = {
		6: 'grid grid-cols-4 gap-3 sm:grid-cols-6',
		8: 'grid grid-cols-4 gap-2.5 sm:grid-cols-6 lg:grid-cols-8',
		12: 'grid grid-cols-6 gap-2 sm:grid-cols-8 lg:grid-cols-12'
	};

	let openId = $state<number | null>(null);
	const ids = $derived(movies.map((m) => m.id));

	function tileClick(e: MouseEvent, id: number) {
		if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
		e.preventDefault();
		openId = id;
	}
</script>

<div class={variant === 'grid' ? GRID[cols] : 'flex gap-3 overflow-x-auto pb-1'}>
	{#each movies as movie (movie.id)}
		<a
			href="{base}/library?movie={movie.id}"
			class="group block {variant === 'shelf' ? shelfWidth : ''}"
			data-panel-item={movie.id}
			data-panel-current={movie.id === openId || undefined}
			title="{movie.title}{movie.year ? ` (${movie.year})` : ''}"
			onclick={(e) => tileClick(e, movie.id)}
		>
			<div class="aspect-[2/3] overflow-hidden rounded-sm border border-border bg-surface-2">
				{#if movie.thumbnail_url}
					<img
						src={movie.thumbnail_url}
						alt={movie.title}
						loading="lazy"
						class="h-full w-full object-cover transition-opacity group-hover:opacity-80"
					/>
				{:else}
					<div class="flex h-full items-center justify-center text-faint">
						<Film size={18} />
					</div>
				{/if}
			</div>
			{#if captions}
				<p class="mt-1 truncate text-xs text-muted group-hover:text-text">{movie.title}</p>
			{/if}
		</a>
	{/each}
</div>

{#if openId !== null}
	<MoviePanel
		movieId={openId}
		dock={false}
		{ids}
		onclose={() => (openId = null)}
		onstep={(id) => (openId = id)}
		onmutated={() => onmutated?.()}
		onremoved={() => {
			openId = null;
			onmutated?.();
		}}
	/>
{/if}
