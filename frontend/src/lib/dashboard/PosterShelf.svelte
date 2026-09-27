<script lang="ts">
	// Recently added as a strip of fixed-size posters: a wide screen shows more of
	// them, and ‹ › scroll it a screenful at a time. A tile opens the film drawer.
	import { base } from '$app/paths';
	import { ChevronLeft, ChevronRight, Film } from '@lucide/svelte';
	import MoviePanel from '$lib/library/MoviePanel.svelte';
	import type { MovieListItem } from './data.svelte';

	let { movies, onmutated }: { movies: MovieListItem[]; onmutated?: () => void } = $props();

	let openId = $state<number | null>(null);
	const ids = $derived(movies.map((m) => m.id));

	let strip = $state<HTMLDivElement>();
	let atStart = $state(true);
	let atEnd = $state(true);

	function measure() {
		if (!strip) return;
		atStart = strip.scrollLeft <= 1;
		atEnd = strip.scrollLeft + strip.clientWidth >= strip.scrollWidth - 1;
	}
	$effect(() => {
		if (!strip) return;
		const ro = new ResizeObserver(measure);
		ro.observe(strip);
		return () => ro.disconnect();
	});

	function scroll(dir: 1 | -1) {
		strip?.scrollBy({ left: dir * strip.clientWidth * 0.9, behavior: 'smooth' });
	}

	function tileClick(e: MouseEvent, id: number) {
		if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
		e.preventDefault();
		openId = id;
	}

	const arrow =
		'shrink-0 rounded-sm p-1.5 text-muted hover:bg-surface-2 hover:text-text disabled:pointer-events-none disabled:opacity-30';
</script>

<div class="flex items-center gap-1">
	{#if !(atStart && atEnd)}
		<button
			type="button"
			class={arrow}
			aria-label="Newer films"
			disabled={atStart}
			onclick={() => scroll(-1)}
		>
			<ChevronLeft size={16} />
		</button>
	{/if}
	<div
		bind:this={strip}
		onscroll={measure}
		class="flex min-w-0 flex-1 gap-2 overflow-x-auto [scrollbar-width:none]"
	>
		{#each movies as movie (movie.id)}
			<a
				href="{base}/library?movie={movie.id}"
				class="group block w-[4.5rem] shrink-0"
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
							<Film size={16} />
						</div>
					{/if}
				</div>
			</a>
		{/each}
	</div>
	{#if !(atStart && atEnd)}
		<button
			type="button"
			class={arrow}
			aria-label="Older films"
			disabled={atEnd}
			onclick={() => scroll(1)}
		>
			<ChevronRight size={16} />
		</button>
	{/if}
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
