<script lang="ts">
	import KioskEmpty from './KioskEmpty.svelte';
	import Poster from './Poster.svelte';
	import type { KioskController } from './controller.svelte';
	import { dayLabel, fmtClock, isRunning } from './time';

	interface Props {
		kiosk: KioskController;
	}
	let { kiosk }: Props = $props();

	let stageW = $state(0);
	let stageH = $state(0);
	let page = $state(0);
	let pageOut = $state(false);

	interface WallFit {
		cols: number;
		rows: number;
		capacity: number;
		tw: number;
		th: number;
		gap: number;
		score: number;
	}

	function bestWallFit(W: number, H: number, n: number): WallFit {
		const gap = Math.max(10, Math.round(Math.min(W, H) * 0.016));
		const pad = gap;
		let best: WallFit | null = null;
		for (let cols = 1; cols <= 14; cols++) {
			const tw = (W - pad * 2 - (cols - 1) * gap) / cols;
			if (tw < 96) break; // posters smaller than this are unreadable across a room
			const th = tw * 1.5;
			const rows = Math.max(1, Math.floor((H - pad * 2 + gap) / (th + gap)));
			const capacity = cols * rows;
			const fitsAll = capacity >= n;
			const score = (fitsAll ? 1e9 : capacity * 1e4) + tw;
			if (!best || score > best.score) {
				best = { cols, rows: Math.min(rows, Math.ceil(n / cols)), capacity, tw, th, gap, score };
			}
		}
		return best || { cols: 1, rows: 1, capacity: 1, tw: 200, th: 300, gap: 12, score: 0 };
	}

	const fit = $derived(bestWallFit(stageW || 1, stageH || 1, kiosk.films.length || 1));
	const pages = $derived(Math.max(1, Math.ceil(kiosk.films.length / fit.capacity)));
	const safePage = $derived(Math.min(page, pages - 1));
	const visible = $derived(
		kiosk.films.slice(safePage * fit.capacity, (safePage + 1) * fit.capacity)
	);

	// Value-stable deps only (pages, dwell), so poll churn never restarts the cadence.
	const dwellMs = $derived(kiosk.prefs.wallPageSecs * 1000);
	$effect(() => {
		page = 0;
		if (pages <= 1) return;
		const timers: ReturnType<typeof setTimeout>[] = [];
		const interval = setInterval(() => {
			pageOut = true;
			timers.push(
				setTimeout(() => {
					page = (page + 1) % pages;
					pageOut = false;
				}, 420)
			);
		}, dwellMs);
		return () => {
			clearInterval(interval);
			timers.forEach(clearTimeout);
			pageOut = false;
		};
	});
</script>

<div class="wall-host" bind:clientWidth={stageW} bind:clientHeight={stageH}>
	{#if !kiosk.films.length}
		<KioskEmpty title="Nothing on the marquee" sub="Check back soon for upcoming showings" />
	{:else}
		<div
			class="wall"
			class:page-out={pageOut}
			style="--cols:{fit.cols};--tw:{fit.tw.toFixed(1)}px;--th:{fit.th.toFixed(
				1
			)}px;--gap:{fit.gap}px"
		>
			{#each visible as film (film.id)}
				{@const showtime = kiosk.prefs.showtimes ? kiosk.showtimeFor(film) : null}
				<article class="tile">
					<Poster {film} cls="tile-poster" />
					<div class="tile-scrim"></div>
					<div class="tile-info">
						<h2>{film.title}</h2>
						<div class="tile-meta">
							{#if film.cert}<span class="cert">{film.cert}</span>{/if}
							{#if film.year}<span>{film.year}</span>{/if}
						</div>
						{#if showtime}
							<div class="tile-time">
								{#if isRunning(showtime, kiosk.now)}
									<span class="live-dot"></span>Now showing
								{:else}
									{dayLabel(showtime.start)} {fmtClock(showtime.start)}
								{/if}
							</div>
						{/if}
					</div>
				</article>
			{/each}
		</div>
	{/if}
</div>
