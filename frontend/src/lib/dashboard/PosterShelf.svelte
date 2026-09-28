<script lang="ts">
	// Recently added as a strip of posters as tall as the card: a wide screen shows
	// more of them, the edges fade where more lie beyond, and ‹ › scroll it a
	// screenful at a time. A tile opens the film drawer.
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

	const fade = $derived(
		`linear-gradient(to right, ${atStart ? '#000' : 'transparent'}, #000 2.5rem, #000 calc(100% - 2.5rem), ${atEnd ? '#000' : 'transparent'})`
	);

	const arrow = 'shrink-0 rounded-sm p-1.5 text-muted hover:bg-surface-2 hover:text-text';
</script>

<div class="flex h-full min-h-36 items-center gap-1">
	<!-- The strip is absolute so the posters take the card's height, never set it. -->
	<button
		type="button"
		class="{arrow} {atStart ? 'invisible' : ''}"
		aria-label="Newer films"
		onclick={() => scroll(-1)}
	>
		<ChevronLeft size={16} />
	</button>
	<div class="relative h-full min-w-0 flex-1">
		<div
			bind:this={strip}
			onscroll={measure}
			class="absolute inset-0 flex gap-2 overflow-x-auto [scrollbar-width:none]"
			style:mask-image={fade}
		>
			{#each movies as movie (movie.id)}
				<a
					href="{base}/library?movie={movie.id}"
					class="group relative block aspect-[2/3] h-full shrink-0 overflow-hidden border border-border
					bg-surface-2"
					data-panel-item={movie.id}
					data-panel-current={movie.id === openId || undefined}
					onclick={(e) => tileClick(e, movie.id)}
				>
					{#if movie.thumbnail_url}
						<img
							src={movie.thumbnail_url}
							alt={movie.title}
							loading="lazy"
							class="h-full w-full object-cover"
						/>
					{:else}
						<div class="flex h-full items-center justify-center text-faint">
							<Film size={16} />
						</div>
					{/if}
					<span
						class="absolute inset-x-0 bottom-0 bg-shell/85 px-1.5 py-1 text-[0.7rem] leading-tight
						opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"
					>
						<span class="line-clamp-2">{movie.title}</span>
						{#if movie.year}<span class="font-mono text-faint">{movie.year}</span>{/if}
					</span>
				</a>
			{/each}
		</div>
	</div>
	<button
		type="button"
		class="{arrow} {atEnd ? 'invisible' : ''}"
		aria-label="Older films"
		onclick={() => scroll(1)}
	>
		<ChevronRight size={16} />
	</button>
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
