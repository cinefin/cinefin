<script lang="ts">
	import { untrack } from 'svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import { base } from '$app/paths';
	import { goto, pushState, replaceState } from '$app/navigation';
	import { page } from '$app/state';
	import {
		Check,
		ChevronLeft,
		ChevronRight,
		ChevronsLeft,
		ChevronsRight,
		Dices,
		Eye,
		EyeOff,
		Film,
		FilterX,
		ListVideo,
		RefreshCw,
		RotateCw,
		Settings,
		Trash2,
		X,
		ZoomIn,
		ZoomOut
	} from '@lucide/svelte';
	import { api, toApiError, unwrap } from '$lib/api/client';
	import { Query, query } from '$lib/api/query.svelte';
	import { unwrapLoose } from '$lib/jobs';
	import type { components } from '$lib/api/types.gen';
	import { formatRuntime } from '$lib/format';
	import { showToast } from '$lib/toast.svelte';
	import { invalidate } from '$lib/invalidate';
	import { display } from '$lib/display.svelte';
	import { sortIndicator, toggleSort, type FilterControl, type SortSpec } from '$lib/filters';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Menu, { type MenuItem } from '$lib/components/ui/Menu.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import FilterBar from '$lib/components/FilterBar.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import MoviePanel, { type MovieFilter } from '$lib/library/MoviePanel.svelte';
	import RandomPickDialog from '$lib/programmes/RandomPickDialog.svelte';
	import type { RandomSlot } from '$lib/programmes/create-types';
	import { playout } from '$lib/stores/playout.svelte';
	import { syncActivity } from '$lib/stores/syncActivity.svelte';

	type MovieListData = components['schemas']['MovieListDataSchema'];

	const DEFAULT_SORT = '-date_added';

	const RUNTIME_BUCKETS: Record<string, { label: string; from?: number; to?: number }> = {
		u90: { label: 'Under 90 min', to: 90 },
		'90-120': { label: '90-120 min', from: 90, to: 120 },
		'120-150': { label: '120-150 min', from: 120, to: 150 },
		o150: { label: 'Over 150 min', from: 150 }
	};

	const SORT_OPTIONS = [
		{ value: '-date_added', label: 'Recently added' },
		{ value: 'date_added', label: 'Oldest first' },
		{ value: 'title', label: 'Title (A-Z)' },
		{ value: '-title', label: 'Title (Z-A)' },
		{ value: '-year', label: 'Year (newest)' },
		{ value: 'year', label: 'Year (oldest)' },
		{ value: '-runtime', label: 'Duration (longest)' },
		{ value: 'runtime', label: 'Duration (shortest)' },
		{ value: '-file_size', label: 'File size (largest)' },
		{ value: 'file_size', label: 'File size (smallest)' },
		{ value: 'random', label: 'Random' }
	];

	// Filter state seeded from the URL so filtered views are shareable.
	const initial = page.url.searchParams;
	const initYear = initial.get('year') ?? '';
	let search = $state(initial.get('search') ?? '');
	let genre = $state(initial.get('genre') ?? '');
	let certification = $state(initial.get('rating') ?? '');
	let resolution = $state(initial.get('resolution') ?? '');
	let yearFrom = $state(initial.get('year_from') ?? initYear);
	let yearTo = $state(initial.get('year_to') ?? initYear);
	let runtime = $state(
		RUNTIME_BUCKETS[initial.get('runtime') ?? ''] ? initial.get('runtime')! : ''
	);
	let sort = $state(
		SORT_OPTIONS.some((o) => o.value === initial.get('sort')) ? initial.get('sort')! : DEFAULT_SORT
	);
	let view = $state<'grid' | 'list'>(localStorage.getItem('lib_view') === 'list' ? 'list' : 'grid');
	let kiosk = $state(['1', '0'].includes(initial.get('kiosk') ?? '') ? initial.get('kiosk')! : '');
	let trailerF = $state(
		['1', '0'].includes(initial.get('trailer') ?? '') ? initial.get('trailer')! : ''
	);
	let tmdbF = $state(
		['present', 'missing'].includes(initial.get('tmdb') ?? '') ? initial.get('tmdb')! : ''
	);

	// A seed pins one shuffle order for a random browse so paging stays
	// consistent; picking Random (or a reload) draws a fresh one.
	const newSeed = () => Math.floor(Math.random() * 2_000_000_000) + 1;
	let randomSeed = $state(newSeed());
	$effect(() => {
		if (sort === 'random') randomSeed = newSeed();
	});

	const SOURCE_SETTINGS = `${base}/settings?tab=library`;

	$effect(() => syncActivity.subscribe());

	// The library's one source, for the in-place Sync button. Kicks a background
	// job and stays put — the topbar "Syncing" lamp reports progress.
	const librarySource = query(() =>
		unwrapLoose<{ source: { id: number; enabled: boolean } | null }>(api.GET('/api/v2/sync/source'))
	);
	const src = $derived(librarySource.data?.source ?? null);
	// Only offer the in-place Sync action for an enabled source; a disabled or
	// absent one sends you to Settings instead of erroring on a dead click.
	const canSync = $derived(!!src?.enabled);
	const sourceId = $derived(src?.id ?? null);

	async function triggerSync(deep = false) {
		if (sourceId == null) return;
		try {
			await unwrapLoose(
				api.POST('/api/v2/sync/sources/{source_id}/runs', {
					params: { path: { source_id: sourceId } },
					body: { operation: 'sync', params: deep ? { deep: true } : {}, max_attempts: 1 }
				})
			);
			showToast(deep ? 'Full re-scan started' : 'Sync started', 'success');
		} catch (e) {
			showToast(toApiError(e).message || 'Could not start the sync', 'error');
		}
	}

	const syncMenuItems = $derived<MenuItem[]>([
		{
			label: 'Full re-scan',
			icon: RotateCw,
			onclick: () => void triggerSync(true),
			disabled: syncActivity.busy
		},
		{ separator: true },
		{
			label: 'Library source & changes…',
			icon: Settings,
			onclick: () => void goto(SOURCE_SETTINGS)
		}
	]);

	// Four poster-width steps, persisted per device. Widths are rem so the
	// density preference scales them too.
	const ZOOM_STEPS = [
		{ key: 's', label: 'S', width: '6.5rem' },
		{ key: 'm', label: 'M', width: '9rem' },
		{ key: 'l', label: 'L', width: '12rem' },
		{ key: 'xl', label: 'XL', width: '16rem' }
	] as const;
	const DEFAULT_ZOOM = 1;
	const storedZoom = ZOOM_STEPS.findIndex((z) => z.key === localStorage.getItem('lib_zoom'));
	let zoomIdx = $state(storedZoom === -1 ? DEFAULT_ZOOM : storedZoom);
	const zoomStep = $derived(ZOOM_STEPS[zoomIdx]);

	function setZoom(idx: number) {
		zoomIdx = Math.min(ZOOM_STEPS.length - 1, Math.max(0, idx));
	}

	$effect(() => {
		localStorage.setItem('lib_zoom', zoomStep.key);
	});

	// A page is a whole number of GRID ROWS: the page size follows the column
	// count. `anchor` is the index of the page's first item, so a resize/zoom
	// lands you back on the same films rather than the same page number.
	const TARGET_ITEMS = 96;
	const LIST_PER_PAGE = 50;
	const GRID_GAP_REM = 1; // gap-4

	let gridWidth = $state(0);
	let pageNum = $state(Math.max(1, parseInt(initial.get('page') ?? '1', 10) || 1));
	let anchor = $state(0);

	/** px per rem — density scales it, so the column maths must follow. */
	const rootFontPx = $derived.by(() => {
		void display.density;
		if (typeof document === 'undefined') return 16;
		return parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
	});

	/** What `repeat(auto-fill, minmax(poster, 1fr))` will actually lay out. */
	const columns = $derived.by(() => {
		const poster = parseFloat(zoomStep.width) * rootFontPx;
		const gap = GRID_GAP_REM * rootFontPx;
		if (!gridWidth || !poster) return 6;
		return Math.max(1, Math.floor((gridWidth + gap) / (poster + gap)));
	});

	const perPage = $derived(
		view === 'list' ? LIST_PER_PAGE : columns * Math.max(2, Math.round(TARGET_ITEMS / columns))
	);

	// The page size changes with the window/zoom/view; keep the same films in
	// front of you rather than the page number.
	$effect(() => {
		const size = perPage;
		const wanted = Math.floor(untrack(() => anchor) / size) + 1;
		if (wanted !== untrack(() => pageNum)) pageNum = wanted;
	});

	function goToPage(next: number): void {
		const target = Math.min(Math.max(1, next), totalPages);
		if (target === pageNum) return;
		pageNum = target;
		anchor = (target - 1) * perPage;
		window.scrollTo({ top: 0, behavior: 'smooth' });
	}

	/** Any filter change starts again at the first page. */
	function setFilter(apply: () => void): void {
		apply();
		pageNum = 1;
		anchor = 0;
	}

	function buildParams() {
		const params: Record<string, string | number | boolean> = {
			page: pageNum,
			per_page: perPage
		};
		if (sort === 'random') {
			params.sort = 'random';
			params.random_seed = randomSeed;
		} else {
			params.sort = sort.startsWith('-') ? sort.slice(1) : sort;
			params.order = sort.startsWith('-') ? 'desc' : 'asc';
		}
		if (search) params.search = search;
		if (genre) params.genre = genre;
		if (certification) params.certification = certification;
		if (resolution) params.resolution = resolution;
		if (kiosk) params.kiosk = kiosk === '1';
		if (trailerF) params.has_trailer = trailerF === '1';
		if (tmdbF) params.tmdb = tmdbF;
		if (yearFrom) params.year_from = yearFrom;
		if (yearTo) params.year_to = yearTo;
		const bucket = RUNTIME_BUCKETS[runtime];
		if (bucket?.from) params.runtime_from = bucket.from;
		if (bucket?.to) params.runtime_to = bucket.to;
		return params;
	}

	const movies = new Query<MovieListData>(() =>
		unwrap(api.GET('/api/v2/movies/list', { params: { query: buildParams() } }))
	);

	// Deps referenced explicitly so the effect tracks them regardless of what
	// the async loader does.
	$effect(() => {
		void [
			search,
			genre,
			certification,
			resolution,
			kiosk,
			trailerF,
			tmdbF,
			yearFrom,
			yearTo,
			runtime,
			sort,
			randomSeed
		];
		void [pageNum, perPage];
		void movies.load();
	});

	$effect(() => movies.live({ keys: ['sync'] }));

	// A single ?year covers from == to.
	function libraryUrl(movieId: number | null): string {
		const p = new URLSearchParams();
		if (search) p.set('search', search);
		if (genre) p.set('genre', genre);
		if (certification) p.set('rating', certification);
		if (resolution) p.set('resolution', resolution);
		if (kiosk) p.set('kiosk', kiosk);
		if (trailerF) p.set('trailer', trailerF);
		if (tmdbF) p.set('tmdb', tmdbF);
		if (yearFrom && yearFrom === yearTo) {
			p.set('year', yearFrom);
		} else {
			if (yearFrom) p.set('year_from', yearFrom);
			if (yearTo) p.set('year_to', yearTo);
		}
		if (runtime) p.set('runtime', runtime);
		if (sort !== DEFAULT_SORT) p.set('sort', sort);
		if (pageNum > 1) p.set('page', String(pageNum));
		if (movieId !== null) p.set('movie', String(movieId));
		const qs = p.toString();
		return `${base}/library${qs ? `?${qs}` : ''}`;
	}

	// replaceState (no history spam) keeps the URL in sync for shareable views.
	$effect(() => {
		const url = libraryUrl(openId);
		// untrack: replaceState touches the router's own reactive state — read
		// inside this effect it would become a self-retriggering dependency.
		untrack(() => {
			try {
				replaceState(url, { movie: openId });
			} catch {
				// Router not ready on the very first tick — the URL already matches.
			}
		});
	});

	// /movies/stats supplies live per-genre / per-certificate counts
	// (supplementary — degrades quietly).
	const stats = query(() => unwrap(api.GET('/api/v2/movies/stats')));
	$effect(() => stats.live({ keys: ['sync'] }));
	const genreCounts = $derived(
		new Map((stats.data?.genres ?? []).map((g) => [g.name, g.movie_count]))
	);
	const certCounts = $derived(
		new Map((stats.data?.certifications ?? []).map((c) => [c.certification, c.count]))
	);

	const currentYear = new Date().getFullYear();
	const years: string[] = [];
	for (let y = currentYear + 1; y >= 1900; y--) years.push(String(y));

	const filterControls = $derived<FilterControl[]>([
		{
			id: 'genre',
			label: 'Genre',
			allLabel: 'All genres',
			value: genre,
			options: (movies.data?.filters.genres ?? []).map((g) => ({
				value: g,
				label: g,
				count: genreCounts.get(g)
			})),
			onchange: (v) => setFilter(() => (genre = v))
		},
		{
			id: 'rating',
			label: 'Rating',
			allLabel: 'All ratings',
			value: certification,
			options: (movies.data?.filters.certifications ?? []).map((c) => ({
				value: c,
				label: c,
				count: certCounts.get(c)
			})),
			onchange: (v) => setFilter(() => (certification = v))
		},
		{
			id: 'year_from',
			label: 'From year',
			allLabel: 'Any',
			value: yearFrom,
			options: years.map((y) => ({ value: y, label: y })),
			onchange: (v) => setFilter(() => (yearFrom = v))
		},
		{
			id: 'year_to',
			label: 'To year',
			allLabel: 'Any',
			value: yearTo,
			options: years.map((y) => ({ value: y, label: y })),
			onchange: (v) => setFilter(() => (yearTo = v))
		},
		{
			id: 'runtime',
			label: 'Runtime',
			allLabel: 'Any',
			value: runtime,
			options: Object.entries(RUNTIME_BUCKETS).map(([value, b]) => ({ value, label: b.label })),
			onchange: (v) => setFilter(() => (runtime = v))
		},
		{
			id: 'resolution',
			label: 'Resolution',
			allLabel: 'All resolutions',
			value: resolution,
			options: (movies.data?.filters.resolutions ?? []).map((r) => ({ value: r, label: r })),
			onchange: (v) => setFilter(() => (resolution = v))
		},
		{
			id: 'kiosk',
			label: 'Kiosk',
			allLabel: 'Any',
			value: kiosk,
			options: [
				{ value: '1', label: 'On kiosk' },
				{ value: '0', label: 'Not on kiosk' }
			],
			onchange: (v) => setFilter(() => (kiosk = v))
		},
		{
			id: 'trailer',
			label: 'Trailer',
			allLabel: 'Any',
			value: trailerF,
			options: [
				{ value: '1', label: 'Has trailer' },
				{ value: '0', label: 'Missing trailer' }
			],
			onchange: (v) => setFilter(() => (trailerF = v))
		},
		{
			id: 'tmdb',
			label: 'TMDB',
			allLabel: 'Any',
			value: tmdbF,
			options: [
				{ value: 'present', label: 'Matched' },
				{ value: 'missing', label: 'No TMDB' }
			],
			onchange: (v) => setFilter(() => (tmdbF = v))
		}
	]);

	const sortSpec = $derived<SortSpec>({
		value: sort,
		options: SORT_OPTIONS,
		default: DEFAULT_SORT,
		onchange: (v) => setFilter(() => (sort = v))
	});

	const filtersActive = $derived(
		Boolean(
			search ||
			genre ||
			certification ||
			resolution ||
			kiosk ||
			trailerF ||
			tmdbF ||
			yearFrom ||
			yearTo ||
			runtime
		)
	);

	function clearFilters() {
		search = '';
		genre = '';
		certification = '';
		resolution = '';
		kiosk = '';
		trailerF = '';
		tmdbF = '';
		yearFrom = '';
		yearTo = '';
		runtime = '';
		sort = DEFAULT_SORT;
	}

	const total = $derived(movies.data?.pagination?.total ?? 0);
	const totalPages = $derived(Math.max(1, Math.ceil(total / perPage)));
	// A filter can shrink the set under the page you are on.
	$effect(() => {
		const pages = totalPages;
		if (untrack(() => pageNum) > pages) {
			pageNum = pages;
			anchor = (pages - 1) * untrack(() => perPage);
		}
	});

	/** The range this page covers, for the pager's own readout. */
	const firstOnPage = $derived(total === 0 ? 0 : (pageNum - 1) * perPage + 1);
	const lastOnPage = $derived(
		Math.min(total, (pageNum - 1) * perPage + (movies.data?.items.length ?? 0))
	);

	const pagerBtn =
		'flex h-8 w-8 items-center justify-center border border-border-strong bg-surface-2 ' +
		'text-muted transition-colors hover:text-text disabled:opacity-35 ' +
		'disabled:pointer-events-none';

	const countText = $derived(
		`${total} ${total === 1 ? 'movie' : 'movies'}${filtersActive ? ' (filtered)' : ''}`
	);

	const sortCols: { key: string; label: string; defaultDesc?: boolean }[] = [
		{ key: 'title', label: 'Title' },
		{ key: 'year', label: 'Year', defaultDesc: true },
		{ key: 'runtime', label: 'Runtime', defaultDesc: true },
		{ key: 'date_added', label: 'Added', defaultDesc: true }
	];

	function headerSort(key: string, defaultDesc?: boolean) {
		sort = toggleSort(sort, key, defaultDesc);
	}

	// The selection deliberately survives filter changes: gather movies from
	// several filtered views into one programme. Clears only via Clear / Escape
	// / bulk delete.
	const selected = new SvelteSet<number>();
	let anchorId: number | null = null; // shift-click range anchor (visible list only)

	const visible = $derived(movies.data?.items ?? []);
	const allVisibleSelected = $derived(
		visible.length > 0 && visible.every((m) => selected.has(m.id))
	);

	function setSelected(id: number, on: boolean) {
		if (on) selected.add(id);
		else selected.delete(id);
	}

	/** Toggle one film; shift extends the last toggle across the visible range. */
	function toggleMovie(id: number, on: boolean, shift: boolean) {
		if (shift && anchorId !== null && anchorId !== id) {
			const a = visible.findIndex((m) => m.id === anchorId);
			const b = visible.findIndex((m) => m.id === id);
			if (a !== -1 && b !== -1) {
				for (let i = Math.min(a, b); i <= Math.max(a, b); i++) setSelected(visible[i].id, on);
				anchorId = id;
				return;
			}
		}
		setSelected(id, on);
		anchorId = id;
	}

	/** Select/deselect everything the current filters show (picks made under
	 *  other filters stay). */
	function toggleAllVisible(on: boolean) {
		visible.forEach((m) => setSelected(m.id, on));
		anchorId = null;
	}

	function clearSelection() {
		selected.clear();
		anchorId = null;
	}

	let bulkBusy = $state(false);
	let confirmDialog: ConfirmDialog;

	/** Every mutation this page performs ends here: silently re-run the current
	 *  list query so a film that no longer matches the active filters drops out
	 *  at once; facet counts follow (supplementary — degrades quietly). */
	async function refreshAfterMutation() {
		await movies.refresh();
		void stats.refresh();
		invalidate('movies');
	}

	function createProgramme() {
		const ids = [...selected];
		if (!ids.length) return;
		void goto(`${base}/programmes/create?movies=${ids.join(',')}`);
	}

	// A filtered browse IS a random-movie query: the filter bar hands it to the
	// wizard as a random slot, drawn when the playlist is generated. Any films
	// already picked ride along, in front of the random slot.
	let randomOpen = $state(false);

	/** The active filters, in the shape the dialog pre-fills from. */
	const randomFromFilters = $derived<Partial<RandomSlot>>({
		genre_names: genre ? [genre] : [],
		certification: certification || null,
		year_from: yearFrom ? parseInt(yearFrom, 10) : null,
		year_to: yearTo ? parseInt(yearTo, 10) : null,
		runtime_from: RUNTIME_BUCKETS[runtime]?.from ?? null,
		runtime_to: RUNTIME_BUCKETS[runtime]?.to ?? null
	});

	function createWithRandom(slot: RandomSlot) {
		const params = new URLSearchParams();
		const ids = [...selected];
		if (ids.length) params.set('movies', ids.join(','));
		params.set('random_movies', JSON.stringify([slot]));
		void goto(`${base}/programmes/create?${params.toString()}`);
	}

	async function bulkKiosk(show: boolean) {
		const ids = [...selected];
		if (!ids.length || bulkBusy) return;
		bulkBusy = true;
		try {
			const res = await unwrap(
				api.POST('/api/v2/movies/bulk-kiosk', { body: { ids, kiosk_display: show } })
			);
			showToast(
				`${res.updated} movie${res.updated === 1 ? '' : 's'} ${show ? 'shown on' : 'hidden from'} the kiosk`,
				'success'
			);
			if (res.missing.length) {
				showToast(
					`${res.missing.length} selected movie${res.missing.length === 1 ? ' is' : 's are'} no longer in the library`,
					'warning'
				);
			}
			await refreshAfterMutation();
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Failed to update kiosk display', 'error');
		} finally {
			bulkBusy = false;
		}
	}

	async function bulkDelete() {
		const ids = [...selected];
		if (!ids.length || bulkBusy) return;
		const noun = ids.length === 1 ? 'movie' : 'movies';
		const ok = await confirmDialog.confirm(
			`Remove ${ids.length} ${noun} from the Cinefin library? Files on disk are not deleted.`,
			{ confirmLabel: 'Remove' }
		);
		if (!ok) return;
		bulkBusy = true;
		try {
			const res = await unwrap(api.POST('/api/v2/movies/bulk-delete', { body: { ids } }));
			clearSelection();
			showToast(
				`${res.deleted} movie${res.deleted === 1 ? '' : 's'} removed from the library`,
				'success'
			);
			if (res.missing.length) {
				showToast(
					`${res.missing.length} selected movie${res.missing.length === 1 ? ' was' : 's were'} already gone`,
					'warning'
				);
			}
			await refreshAfterMutation();
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Failed to remove the selected movies', 'error');
		} finally {
			bulkBusy = false;
		}
	}

	function onWindowKeydown(e: KeyboardEvent) {
		// The confirm dialog and the film drawer own Escape while open.
		if (
			e.key === 'Escape' &&
			selected.size &&
			openId === null &&
			!document.querySelector('dialog[open]')
		) {
			clearSelection();
		}
	}

	// The open film rides SvelteKit shallow routing: opening pushes a history
	// entry so Back closes the drawer; stepping prev/next replaces it; a deep
	// link opens it on load. `openId` derives from page.state (restored on
	// Back/Forward) — not page.url, which shallow push/replaceState leave
	// untouched; the initial entry has no state yet, so it falls back to the bar.
	function parseMovieParam(raw: string | null): number | null {
		const id = Number(raw);
		return raw && Number.isInteger(id) && id > 0 ? id : null;
	}
	const openId = $derived.by(() => {
		const fromState = page.state.movie;
		if (fromState !== undefined) return fromState;
		return parseMovieParam(new URL(location.href).searchParams.get('movie'));
	});
	let modalPushed = false; // we pushed a history entry → Back pops it
	$effect(() => {
		if (openId === null) modalPushed = false;
	});

	function openMovie(id: number) {
		if (openId === null) {
			pushState(libraryUrl(id), { movie: id });
			modalPushed = true;
		} else {
			replaceState(libraryUrl(id), { movie: id });
		}
	}

	function closeMovie() {
		if (openId === null) return;
		if (modalPushed) {
			modalPushed = false;
			history.back();
		} else {
			replaceState(libraryUrl(null), { movie: null });
		}
	}

	/** Plain click opens the drawer; shift-click extends the selection;
	 *  meta/ctrl-click keeps open-in-new-tab on the deep link. */
	function cardClick(e: MouseEvent, id: number) {
		if (e.metaKey || e.ctrlKey || e.button !== 0) return;
		e.preventDefault();
		if (e.shiftKey) {
			toggleMovie(id, true, true);
			return;
		}
		openMovie(id);
	}

	/** Click-to-filter from the drawer: apply the facet in place and close. */
	function applyMovieFilter(f: MovieFilter) {
		// setFilter so paging resets to the first page, like the toolbar filters.
		setFilter(() => {
			if (f.kind === 'year') yearFrom = yearTo = String(f.value);
			else if (f.kind === 'search') search = f.value;
			else if (f.kind === 'genre') genre = f.value;
			else certification = f.value;
		});
		closeMovie();
	}

	function onMovieRemoved(id: number) {
		selected.delete(id);
		closeMovie();
		void refreshAfterMutation();
	}
</script>

<svelte:head><title>Library - Cinefin</title></svelte:head>

<svelte:window onkeydown={onWindowKeydown} />

<div class="mb-3 flex flex-wrap items-center gap-2">
	<h1 class="mr-auto text-lg font-semibold">Library</h1>
	{#if canSync}
		<div class="inline-flex items-stretch">
			<Button
				class="rounded-r-none"
				disabled={syncActivity.busy}
				title="Sync new and changed films in the background"
				onclick={() => void triggerSync(false)}
			>
				<RefreshCw size={13} />
				{syncActivity.busy ? 'Syncing…' : 'Sync'}
			</Button>
			<Menu
				caretOnly
				ariaLabel="More sync options"
				align="right"
				class="-ml-px rounded-l-none"
				items={syncMenuItems}
			/>
		</div>
	{:else}
		<Button href={SOURCE_SETTINGS} title="Your library source and its last sync">
			<RefreshCw size={13} /> Sync
		</Button>
	{/if}
</div>

<FilterBar
	search={{
		value: search,
		placeholder: 'Search movies, directors…',
		onchange: (v) => setFilter(() => (search = v))
	}}
	filters={filterControls}
	sort={sortSpec}
	count={countText}
	bind:view
	viewKey="lib_view"
	onreset={clearFilters}
>
	<Button
		variant="ghost"
		title="Create a programme with a random movie from these filters"
		onclick={() => (randomOpen = true)}
	>
		<Dices size={14} /> Random movie
	</Button>

	{#snippet viewExtras()}
		{#if view === 'grid'}
			<div class="flex border border-border-strong" role="group" aria-label="Poster size">
				<button
					type="button"
					title="Smaller posters"
					aria-label="Smaller posters"
					disabled={zoomIdx === 0}
					onclick={() => setZoom(zoomIdx - 1)}
					class="flex h-9 w-9 items-center justify-center bg-surface-2 text-muted
						hover:text-text active:brightness-90 disabled:opacity-40 disabled:hover:text-muted"
				>
					<ZoomOut size={15} />
				</button>
				<span
					class="flex h-9 min-w-8 items-center justify-center border-x border-border-strong
						bg-surface-2 px-1.5 font-mono text-[0.65rem] text-muted"
					aria-live="polite"
					title="Poster size: {zoomStep.label}"
				>
					{zoomStep.label}
				</span>
				<button
					type="button"
					title="Larger posters"
					aria-label="Larger posters"
					disabled={zoomIdx === ZOOM_STEPS.length - 1}
					onclick={() => setZoom(zoomIdx + 1)}
					class="flex h-9 w-9 items-center justify-center bg-surface-2 text-muted
						hover:text-text active:brightness-90 disabled:opacity-40 disabled:hover:text-muted"
				>
					<ZoomIn size={15} />
				</button>
			</div>
		{/if}
	{/snippet}
</FilterBar>

{#if selected.size}
	<!-- Sticks under the topbar (h-14): a selection is gathered while scrolling,
	     so the actions must stay reachable. z-20 clears the posters' own z-10
	     select toggles. -->
	<div
		class="sticky top-14 z-20 mb-3 flex flex-wrap items-center gap-2 border border-l-2
			border-border-strong border-l-accent bg-surface-2 px-3 py-2"
	>
		<span class="font-mono text-xs text-accent">{selected.size} selected</span>
		<span class="h-4 w-px bg-border-strong" aria-hidden="true"></span>
		<Button size="sm" variant="primary" onclick={createProgramme}>
			<ListVideo size={13} /> Create programme
		</Button>
		<Button
			size="sm"
			disabled={bulkBusy}
			title="Show the selected movies on the kiosk display"
			onclick={() => void bulkKiosk(true)}
		>
			<Eye size={13} /> Kiosk on
		</Button>
		<Button
			size="sm"
			disabled={bulkBusy}
			title="Hide the selected movies from the kiosk display"
			onclick={() => void bulkKiosk(false)}
		>
			<EyeOff size={13} /> Kiosk off
		</Button>
		<Button
			size="sm"
			variant="danger"
			disabled={bulkBusy}
			title="Remove the selected movies from the library (files on disk are untouched)"
			onclick={() => void bulkDelete()}
		>
			<Trash2 size={13} /> Remove from library
		</Button>
		<span class="ml-auto flex items-center gap-2">
			<Button
				size="sm"
				variant="ghost"
				disabled={allVisibleSelected}
				title="Select every movie on this page"
				onclick={() => toggleAllVisible(true)}
			>
				Select page
			</Button>
			<Button size="sm" variant="ghost" title="Clear selection (Esc)" onclick={clearSelection}>
				<X size={13} /> Clear
			</Button>
		</span>
	</div>
{/if}

{#if movies.loading}
	<Spinner label="Loading movies…" />
{:else if movies.error}
	<ErrorState error={movies.error} retry={() => void movies.load()} />
{:else if !movies.data?.items.length}
	{#if filtersActive}
		<EmptyState
			icon={FilterX}
			title="No movies match your filters"
			message="Try different terms, or clear the filters to see the whole library."
		>
			{#snippet action()}
				<Button onclick={clearFilters}>Clear filters</Button>
			{/snippet}
		</EmptyState>
	{:else}
		<EmptyState
			icon={Film}
			title="No movies yet"
			message="Connect your Jellyfin or Plex server to sync movies into the library."
		>
			{#snippet action()}
				<Button variant="primary" href={SOURCE_SETTINGS}>Add a media source</Button>
			{/snippet}
		</EmptyState>
	{/if}
{:else if view === 'grid'}
	<!-- min(…,100%) keeps XL from overflowing a container narrower than one poster. -->
	<div
		bind:clientWidth={gridWidth}
		class="grid grid-cols-[repeat(auto-fill,minmax(min(var(--poster-w),100%),1fr))] gap-4"
		style="--poster-w: {zoomStep.width}"
	>
		{#each movies.data.items as movie (movie.id)}
			<a
				href="{base}/library?movie={movie.id}"
				class="group block"
				data-panel-item={movie.id}
				data-panel-current={movie.id === openId || undefined}
				onclick={(e) => cardClick(e, movie.id)}
			>
				<div
					class="relative aspect-[2/3] overflow-hidden border border-l-2 bg-surface-2
						{selected.has(movie.id)
						? 'border-border-strong border-l-accent'
						: 'border-border border-l-transparent'}"
				>
					<button
						type="button"
						class="absolute top-1 left-1 z-10 flex h-5 w-5 items-center justify-center border
							transition-opacity
							{selected.has(movie.id)
							? 'border-accent bg-accent text-on-accent opacity-100'
							: `border-border-strong bg-bg/80 text-transparent hover:text-muted focus-visible:opacity-100 ${
									selected.size ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'
								}`}"
						aria-pressed={selected.has(movie.id)}
						aria-label="{selected.has(movie.id) ? 'Deselect' : 'Select'} {movie.title}"
						onclick={(e) => {
							e.preventDefault();
							e.stopPropagation();
							toggleMovie(movie.id, !selected.has(movie.id), e.shiftKey);
						}}
					>
						<Check size={12} strokeWidth={3} />
					</button>
					{#if movie.thumbnail_url}
						<img
							src={movie.thumbnail_url}
							alt={movie.title}
							loading="lazy"
							class="h-full w-full object-cover transition-opacity group-hover:opacity-80"
						/>
					{:else}
						<div class="flex h-full items-center justify-center text-faint">
							<Film size={24} />
						</div>
					{/if}
					{#if movie.certification}
						<span class="absolute right-1 bottom-1">
							<Badge variant="outline" class="bg-bg/80">{movie.certification}</Badge>
						</span>
					{/if}
					{#if movie.tmdbid === 0}
						<span class="absolute top-1 right-1">
							<Badge variant="outline" class="bg-bg/80">No TMDB</Badge>
						</span>
					{/if}
				</div>
				<p class="mt-1.5 truncate text-sm group-hover:text-accent">{movie.title}</p>
				<p class="text-xs text-muted">
					{movie.year ?? '-'}{movie.runtime ? ` · ${movie.runtime} min` : ''}
				</p>
			</a>
		{/each}
	</div>
{:else}
	<div class="overflow-x-auto border border-border">
		<table class="w-full text-sm">
			<thead>
				<tr class="border-b border-border bg-surface-2 text-left text-xs font-medium text-muted">
					<th class="w-8 border-l-2 border-l-transparent px-3 py-2">
						<input
							type="checkbox"
							aria-label="Select all movies"
							class="block accent-accent"
							checked={allVisibleSelected}
							onclick={(e) => toggleAllVisible((e.currentTarget as HTMLInputElement).checked)}
						/>
					</th>
					<th class="w-12 px-3 py-2"></th>
					{#each sortCols.slice(0, 2) as col (col.key)}
						<th class="px-3 py-2">
							<button
								type="button"
								class="hover:text-text
									{sort === col.key || sort === `-${col.key}` ? 'text-accent' : ''}"
								onclick={() => headerSort(col.key, col.defaultDesc)}
							>
								{col.label}
								{sortIndicator(sort, col.key)}
							</button>
						</th>
					{/each}
					<th class="px-3 py-2">Director</th>
					{#each sortCols.slice(2) as col (col.key)}
						<th class="px-3 py-2">
							<button
								type="button"
								class="hover:text-text
									{sort === col.key || sort === `-${col.key}` ? 'text-accent' : ''}"
								onclick={() => headerSort(col.key, col.defaultDesc)}
							>
								{col.label}
								{sortIndicator(sort, col.key)}
							</button>
						</th>
					{/each}
					<th class="px-3 py-2">Cert</th>
					<th class="px-3 py-2">Genres</th>
				</tr>
			</thead>
			<tbody class="divide-y divide-border">
				{#each movies.data.items as movie (movie.id)}
					<tr
						class="cursor-pointer hover:bg-surface-2 {selected.has(movie.id)
							? 'bg-surface-2/60'
							: ''}"
						data-panel-item={movie.id}
						data-panel-current={movie.id === openId || undefined}
						onclick={(e) => cardClick(e, movie.id)}
					>
						<!-- Clicks in this cell never navigate; shift-click extends the toggle. -->
						<td
							class="border-l-2 px-3 py-1.5 {selected.has(movie.id)
								? 'border-l-accent'
								: 'border-l-transparent'}"
							onclick={(e) => e.stopPropagation()}
						>
							<input
								type="checkbox"
								aria-label="Select {movie.title}"
								class="block accent-accent"
								checked={selected.has(movie.id)}
								onclick={(e) => {
									e.stopPropagation();
									toggleMovie(movie.id, (e.currentTarget as HTMLInputElement).checked, e.shiftKey);
								}}
							/>
						</td>
						<td class="px-3 py-1.5">
							{#if movie.thumbnail_url}
								<img
									src={movie.thumbnail_url}
									alt=""
									loading="lazy"
									class="h-10 w-7 border border-border object-cover"
								/>
							{:else}
								<span
									class="flex h-10 w-7 items-center justify-center border border-border
										bg-surface-2 text-faint"
								>
									<Film size={12} />
								</span>
							{/if}
						</td>
						<td class="max-w-72 truncate px-3 py-1.5">
							<a
								href="{base}/library?movie={movie.id}"
								class="hover:text-accent"
								onclick={(e) => {
									e.stopPropagation();
									cardClick(e, movie.id);
								}}
							>
								{movie.title}
							</a>
						</td>
						<td class="px-3 py-1.5 font-mono text-xs">{movie.year ?? ''}</td>
						<td class="max-w-44 truncate px-3 py-1.5 text-xs text-muted">{movie.director ?? ''}</td>
						<td class="px-3 py-1.5 font-mono text-xs whitespace-nowrap">
							{movie.runtime ? formatRuntime(movie.runtime) : ''}
						</td>
						<td class="px-3 py-1.5 font-mono text-xs whitespace-nowrap text-muted">
							{movie.date_added ? new Date(movie.date_added).toLocaleDateString() : ''}
						</td>
						<td class="px-3 py-1.5">
							<span class="inline-flex items-center gap-1">
								{#if movie.certification}
									<Badge variant="outline">{movie.certification}</Badge>
								{/if}
								{#if movie.tmdbid === 0}
									<Badge variant="outline">No TMDB</Badge>
								{/if}
							</span>
						</td>
						<td class="max-w-56 truncate px-3 py-1.5 text-xs text-muted">
							{(movie.genres ?? []).join(', ')}
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{/if}

{#if !movies.loading && !movies.error && movies.data?.items.length}
	<nav
		class="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3"
		aria-label="Library pages"
	>
		<span class="font-mono text-xs text-muted">
			{firstOnPage}-{lastOnPage} of {total}
		</span>
		{#if totalPages > 1}
			<div class="flex items-center gap-1">
				<button
					type="button"
					class={pagerBtn}
					disabled={pageNum === 1}
					aria-label="First page"
					title="First page"
					onclick={() => goToPage(1)}
				>
					<ChevronsLeft size={15} />
				</button>
				<button
					type="button"
					class={pagerBtn}
					disabled={pageNum === 1}
					aria-label="Previous page"
					title="Previous page"
					onclick={() => goToPage(pageNum - 1)}
				>
					<ChevronLeft size={15} />
				</button>
				<span class="px-2 font-mono text-xs text-muted" aria-current="page">
					{pageNum} / {totalPages}
				</span>
				<button
					type="button"
					class={pagerBtn}
					disabled={pageNum === totalPages}
					aria-label="Next page"
					title="Next page"
					onclick={() => goToPage(pageNum + 1)}
				>
					<ChevronRight size={15} />
				</button>
				<button
					type="button"
					class={pagerBtn}
					disabled={pageNum === totalPages}
					aria-label="Last page"
					title="Last page"
					onclick={() => goToPage(totalPages)}
				>
					<ChevronsRight size={15} />
				</button>
			</div>
		{/if}
	</nav>
{/if}

{#if openId !== null}
	<MoviePanel
		movieId={openId}
		history={false}
		ids={visible.map((m) => m.id)}
		selected={selected.has(openId)}
		selectedIds={[...selected]}
		onclose={closeMovie}
		onstep={openMovie}
		onselect={() => toggleMovie(openId!, !selected.has(openId!), false)}
		onfilter={applyMovieFilter}
		onmutated={() => void refreshAfterMutation()}
		onremoved={() => onMovieRemoved(openId!)}
	/>
{/if}

<RandomPickDialog
	bind:open={randomOpen}
	initial={randomFromFilters}
	confirmLabel="Create programme"
	onconfirm={createWithRandom}
/>

<ConfirmDialog bind:this={confirmDialog} title="Remove from library" />
