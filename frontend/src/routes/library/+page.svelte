<script lang="ts">
	import PageHeader from '$lib/components/shell/PageHeader.svelte';
	import { untrack } from 'svelte';
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
	import { api, unwrap } from '$lib/api/client';
	import { Query, query } from '$lib/api/query.svelte';
	import { unwrapLoose } from '$lib/jobs';
	import type { components } from '$lib/api/types.gen';
	import { formatRuntime, formatSize } from '$lib/format';
	import { showToast } from '$lib/toast.svelte';
	import { attempt } from '$lib/settings/form.svelte';
	import { Selection } from '$lib/selection.svelte';
	import { invalidate } from '$lib/invalidate';
	import { display } from '$lib/display.svelte';
	import {
		sortIndicator,
		toggleSort,
		type FilterControl,
		type FilterOption,
		type SortSpec
	} from '$lib/filters';
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
	const pick = (key: string, allowed: string[], fallback = '') => {
		const v = initial.get(key) ?? '';
		return allowed.includes(v) ? v : fallback;
	};
	const filters = $state({
		search: initial.get('search') ?? '',
		genre: initial.get('genre') ?? '',
		certification: initial.get('rating') ?? '',
		resolution: initial.get('resolution') ?? '',
		yearFrom: initial.get('year_from') ?? initYear,
		yearTo: initial.get('year_to') ?? initYear,
		runtime: pick('runtime', Object.keys(RUNTIME_BUCKETS)),
		kiosk: pick('kiosk', ['1', '0']),
		trailer: pick('trailer', ['1', '0']),
		tmdb: pick('tmdb', ['present', 'missing'])
	});
	type FilterKey = keyof typeof filters;
	// Filter → [URL param, API param], in URL order; kiosk and trailer reach the API as booleans.
	const PARAMS: [FilterKey, string, string][] = [
		['search', 'search', 'search'],
		['genre', 'genre', 'genre'],
		['certification', 'rating', 'certification'],
		['resolution', 'resolution', 'resolution'],
		['kiosk', 'kiosk', 'kiosk'],
		['trailer', 'trailer', 'has_trailer'],
		['tmdb', 'tmdb', 'tmdb'],
		['yearFrom', 'year_from', 'year_from'],
		['yearTo', 'year_to', 'year_to']
	];
	const sortValues = SORT_OPTIONS.map((o) => o.value);
	let sort = $state(pick('sort', sortValues, DEFAULT_SORT));
	let view = $state<'grid' | 'list'>(localStorage.getItem('lib_view') === 'list' ? 'list' : 'grid');

	// A seed pins one shuffle order so random paging stays consistent.
	const newSeed = () => Math.floor(Math.random() * 2_000_000_000) + 1;
	let randomSeed = $state(newSeed());
	$effect(() => {
		if (sort === 'random') randomSeed = newSeed();
	});

	const SOURCE_SETTINGS = `${base}/settings?tab=library`;

	$effect(() => syncActivity.subscribe());

	// The in-place Sync kicks a background job (the topbar lamp reports progress);
	// a disabled or absent source sends you to Settings instead.
	const librarySource = query(() =>
		unwrapLoose<{ source: { id: number; enabled: boolean } | null }>(api.GET('/api/v2/sync/source'))
	);
	const src = $derived(librarySource.data?.source ?? null);

	async function triggerSync(deep = false) {
		if (!src) return;
		await attempt(async () => {
			await unwrapLoose(
				api.POST('/api/v2/sync/sources/{source_id}/runs', {
					params: { path: { source_id: src.id } },
					body: { operation: 'sync', params: deep ? { deep: true } : {}, max_attempts: 1 }
				})
			);
			showToast(deep ? 'Full re-scan started' : 'Sync started', 'success');
		}, 'Could not start the sync');
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

	// Poster widths in rem so the density preference scales them too.
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

	// A page is a whole number of grid rows. `anchor` (the page's first index) keeps
	// the same films in front of you when the page size changes.
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
		for (const [key, , apiKey] of PARAMS) {
			const v = filters[key];
			if (v) params[apiKey] = key === 'kiosk' || key === 'trailer' ? v === '1' : v;
		}
		const bucket = RUNTIME_BUCKETS[filters.runtime];
		if (bucket?.from) params.runtime_from = bucket.from;
		if (bucket?.to) params.runtime_to = bucket.to;
		return params;
	}

	const movies = new Query<MovieListData>(() =>
		unwrap(api.GET('/api/v2/movies/list', { params: { query: buildParams() } }))
	);

	// Deps referenced explicitly: the async loader's reads aren't tracked.
	$effect(() => {
		void [Object.values(filters), sort, randomSeed, pageNum, perPage];
		void movies.load();
	});

	$effect(() => movies.live({ keys: ['sync'] }));

	// A single ?year covers from == to.
	function libraryUrl(movieId: number | null): string {
		const p = new URLSearchParams();
		const f = filters;
		for (const [key, urlKey] of PARAMS)
			if (f[key] && !key.startsWith('year')) p.set(urlKey, f[key]);
		if (f.yearFrom && f.yearFrom === f.yearTo) {
			p.set('year', f.yearFrom);
		} else {
			if (f.yearFrom) p.set('year_from', f.yearFrom);
			if (f.yearTo) p.set('year_to', f.yearTo);
		}
		if (f.runtime) p.set('runtime', f.runtime);
		if (sort !== DEFAULT_SORT) p.set('sort', sort);
		if (pageNum > 1) p.set('page', String(pageNum));
		if (movieId !== null) p.set('movie', String(movieId));
		const qs = p.toString();
		return `${base}/library${qs ? `?${qs}` : ''}`;
	}

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

	// Per-genre / per-certificate counts (supplementary).
	const stats = query(() => unwrap(api.GET('/api/v2/movies/stats')));
	$effect(() => stats.live({ keys: ['sync'] }));
	const genreCounts = $derived(
		new Map((stats.data?.genres ?? []).map((g) => [g.name, g.movie_count]))
	);
	const certCounts = $derived(
		new Map((stats.data?.certifications ?? []).map((c) => [c.certification, c.count]))
	);

	const currentYear = new Date().getFullYear();
	const years = Array.from({ length: currentYear + 2 - 1900 }, (_, i) => {
		const y = String(currentYear + 1 - i);
		return { value: y, label: y };
	});
	const opts = (values: string[] | undefined, counts?: Map<string, number>) =>
		(values ?? []).map((v) => ({ value: v, label: v, count: counts?.get(v) }));

	const runtimeOptions = Object.entries(RUNTIME_BUCKETS).map(([value, b]) => ({
		value,
		label: b.label
	}));
	const pair = (a: string, aLabel: string, b: string, bLabel: string) => [
		{ value: a, label: aLabel },
		{ value: b, label: bLabel }
	];

	function control(
		key: FilterKey,
		label: string,
		allLabel: string,
		options: FilterOption[],
		id: string = key
	): FilterControl {
		const onchange = (v: string) => setFilter(() => (filters[key] = v));
		return { id, label, allLabel, value: filters[key], options, onchange };
	}

	const filterControls = $derived.by<FilterControl[]>(() => {
		const f = movies.data?.filters;
		return [
			control('genre', 'Genre', 'All genres', opts(f?.genres, genreCounts)),
			control(
				'certification',
				'Rating',
				'All ratings',
				opts(f?.certifications, certCounts),
				'rating'
			),
			control('yearFrom', 'From year', 'Any', years, 'year_from'),
			control('yearTo', 'To year', 'Any', years, 'year_to'),
			control('runtime', 'Runtime', 'Any', runtimeOptions),
			control('resolution', 'Resolution', 'All resolutions', opts(f?.resolutions)),
			control('kiosk', 'Kiosk', 'Any', pair('1', 'On kiosk', '0', 'Not on kiosk')),
			control('trailer', 'Trailer', 'Any', pair('1', 'Has trailer', '0', 'Missing trailer')),
			control('tmdb', 'TMDB', 'Any', pair('present', 'Matched', 'missing', 'No TMDB'))
		];
	});

	const sortSpec = $derived<SortSpec>({
		value: sort,
		options: SORT_OPTIONS,
		default: DEFAULT_SORT,
		onchange: (v) => setFilter(() => (sort = v))
	});

	const filtersActive = $derived(Object.values(filters).some(Boolean));

	function clearFilters() {
		for (const k in filters) filters[k as FilterKey] = '';
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

	const firstOnPage = $derived(total === 0 ? 0 : (pageNum - 1) * perPage + 1);
	const lastOnPage = $derived(
		Math.min(total, (pageNum - 1) * perPage + (movies.data?.items.length ?? 0))
	);

	const countText = $derived(
		`${total} ${total === 1 ? 'movie' : 'movies'}${filtersActive ? ' (filtered)' : ''}`
	);

	const sortCols: { key: string; label: string; defaultDesc?: boolean }[] = [
		{ key: 'title', label: 'Title' },
		{ key: 'year', label: 'Year', defaultDesc: true },
		{ key: 'runtime', label: 'Runtime', defaultDesc: true },
		{ key: 'date_added', label: 'Added', defaultDesc: true },
		{ key: 'file_size', label: 'Size', defaultDesc: true }
	];

	// The selection survives filter changes, to gather films from several views.
	const visible = $derived(movies.data?.items ?? []);
	const selected = new Selection(() => visible);

	let bulkBusy = $state(false);
	let confirmDialog: ConfirmDialog;

	/** After any mutation: a film that no longer matches drops out at once. */
	async function refreshAfterMutation() {
		await movies.refresh();
		void stats.refresh();
		invalidate('movies');
	}

	function createProgramme() {
		const ids = [...selected];
		if (!ids.length) return;
		void goto(`${base}/programmes/new?movies=${ids.join(',')}`);
	}

	// A filtered browse IS a random-movie query, handed to the new programme as a random slot
	// (picked films ride along in front of it).
	let randomOpen = $state(false);

	const randomFromFilters = $derived<Partial<RandomSlot>>({
		genre_names: filters.genre ? [filters.genre] : [],
		certification: filters.certification || null,
		year_from: filters.yearFrom ? parseInt(filters.yearFrom, 10) : null,
		year_to: filters.yearTo ? parseInt(filters.yearTo, 10) : null,
		runtime_from: RUNTIME_BUCKETS[filters.runtime]?.from ?? null,
		runtime_to: RUNTIME_BUCKETS[filters.runtime]?.to ?? null
	});

	function createWithRandom(slot: RandomSlot) {
		const params = new URLSearchParams();
		const ids = [...selected];
		if (ids.length) params.set('movies', ids.join(','));
		params.set('random_movies', JSON.stringify([slot]));
		void goto(`${base}/programmes/new?${params.toString()}`);
	}

	const films = (n: number) => `${n} movie${n === 1 ? '' : 's'}`;

	async function bulk(run: (ids: number[]) => Promise<void>, failed: string) {
		const ids = [...selected];
		if (!ids.length || bulkBusy) return;
		bulkBusy = true;
		try {
			await run(ids);
			await refreshAfterMutation();
		} catch (e) {
			showToast(e instanceof Error ? e.message : failed, 'error');
		} finally {
			bulkBusy = false;
		}
	}

	const bulkKiosk = (show: boolean) =>
		bulk(async (ids) => {
			const res = await unwrap(
				api.POST('/api/v2/movies/bulk-kiosk', { body: { ids, kiosk_display: show } })
			);
			showToast(`${films(res.updated)} ${show ? 'shown on' : 'hidden from'} the kiosk`, 'success');
			const n = res.missing.length;
			if (n)
				showToast(
					`${n} selected movie${n === 1 ? ' is' : 's are'} no longer in the library`,
					'warning'
				);
		}, 'Failed to update kiosk display');

	async function bulkDelete() {
		if (!selected.size || bulkBusy) return;
		const ok = await confirmDialog.confirm(
			`Remove ${films(selected.size)} from the Cinefin library? Files on disk are not deleted.`,
			{ confirmLabel: 'Remove' }
		);
		if (!ok) return;
		await bulk(async (ids) => {
			const res = await unwrap(api.POST('/api/v2/movies/bulk-delete', { body: { ids } }));
			selected.clear();
			showToast(`${films(res.deleted)} removed from the library`, 'success');
			const n = res.missing.length;
			if (n) showToast(`${n} selected movie${n === 1 ? ' was' : 's were'} already gone`, 'warning');
		}, 'Failed to remove the selected movies');
	}

	function onWindowKeydown(e: KeyboardEvent) {
		// The confirm dialog and the film drawer own Escape while open.
		if (
			e.key === 'Escape' &&
			selected.size &&
			openId === null &&
			!document.querySelector('dialog[open]')
		) {
			selected.clear();
		}
	}

	// The open film rides shallow routing (opening pushes, so Back closes; stepping
	// replaces). page.state carries it; the first entry has none, so read the bar.
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

	/** Click opens the drawer, shift-click selects, meta/ctrl-click follows the link. */
	function cardClick(e: MouseEvent, id: number) {
		if (e.metaKey || e.ctrlKey || e.button !== 0) return;
		e.preventDefault();
		if (e.shiftKey) {
			selected.toggle(id, true, true);
			return;
		}
		openMovie(id);
	}

	function applyMovieFilter(f: MovieFilter) {
		setFilter(() => {
			if (f.kind === 'year') filters.yearFrom = filters.yearTo = String(f.value);
			else if (f.kind === 'search') filters.search = f.value;
			else if (f.kind === 'genre') filters.genre = f.value;
			else filters.certification = f.value;
		});
		closeMovie();
	}

	function onMovieRemoved(id: number) {
		selected.delete(id);
		closeMovie();
		void refreshAfterMutation();
	}
</script>

<svelte:window onkeydown={onWindowKeydown} />

<PageHeader title="Library" {actions} />
{#snippet actions()}
	{#if src?.enabled}
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
{/snippet}

{#snippet zoomBtn(label: string, Icon: typeof ZoomIn, disabled: boolean, step: number)}
	<button
		type="button"
		title={label}
		aria-label={label}
		{disabled}
		onclick={() => setZoom(zoomIdx + step)}
		class="flex h-9 w-9 items-center justify-center bg-surface-2 text-muted
			hover:text-text active:brightness-90 disabled:opacity-40 disabled:hover:text-muted"
	>
		<Icon size={15} />
	</button>
{/snippet}

<FilterBar
	search={{
		value: filters.search,
		placeholder: 'Search movies, directors…',
		onchange: (v) => setFilter(() => (filters.search = v))
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
				{@render zoomBtn('Smaller posters', ZoomOut, zoomIdx === 0, -1)}
				<span
					class="flex h-9 min-w-8 items-center justify-center border-x border-border-strong
						bg-surface-2 px-1.5 font-mono text-[0.65rem] text-muted"
					aria-live="polite"
					title="Poster size: {zoomStep.label}"
				>
					{zoomStep.label}
				</span>
				{@render zoomBtn('Larger posters', ZoomIn, zoomIdx === ZOOM_STEPS.length - 1, 1)}
			</div>
		{/if}
	{/snippet}
</FilterBar>

{#if selected.size}
	<!-- Sticky under the topbar; z-20 clears the posters' z-10 select toggles. -->
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
				disabled={selected.allVisible}
				title="Select every movie on this page"
				onclick={() => selected.setVisible(true)}
			>
				Select page
			</Button>
			<Button
				size="sm"
				variant="ghost"
				title="Clear selection (Esc)"
				onclick={() => selected.clear()}
			>
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
		{#each visible as movie (movie.id)}
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
							selected.toggle(movie.id, !selected.has(movie.id), e.shiftKey);
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
	{#snippet sortTh(col: (typeof sortCols)[number])}
		<th class="px-3 py-2">
			<button
				type="button"
				class="hover:text-text
					{sort === col.key || sort === `-${col.key}` ? 'text-accent' : ''}"
				onclick={() => (sort = toggleSort(sort, col.key, col.defaultDesc))}
			>
				{col.label}
				{sortIndicator(sort, col.key)}
			</button>
		</th>
	{/snippet}
	<div class="overflow-x-auto border border-border">
		<table class="w-full text-sm">
			<thead>
				<tr class="border-b border-border bg-surface-2 text-left text-xs font-medium text-muted">
					<th class="w-8 border-l-2 border-l-transparent px-3 py-2">
						<input
							type="checkbox"
							aria-label="Select all movies"
							class="block accent-accent"
							checked={selected.allVisible}
							onclick={(e) => selected.setVisible((e.currentTarget as HTMLInputElement).checked)}
						/>
					</th>
					<th class="w-12 px-3 py-2"></th>
					{#each sortCols.slice(0, 2) as col (col.key)}
						{@render sortTh(col)}
					{/each}
					<th class="px-3 py-2">Director</th>
					{#each sortCols.slice(2) as col (col.key)}
						{@render sortTh(col)}
					{/each}
					<th class="px-3 py-2">Cert</th>
					<th class="px-3 py-2">Genres</th>
				</tr>
			</thead>
			<tbody class="divide-y divide-border">
				{#each visible as movie (movie.id)}
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
									selected.toggle(
										movie.id,
										(e.currentTarget as HTMLInputElement).checked,
										e.shiftKey
									);
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
						<td class="px-3 py-1.5 font-mono text-xs whitespace-nowrap text-muted">
							{formatSize(movie.file_size)}
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

{#snippet pagerBtn(label: string, Icon: typeof ZoomIn, disabled: boolean, to: number)}
	<button
		type="button"
		class="flex h-8 w-8 items-center justify-center border border-border-strong bg-surface-2
			text-muted transition-colors hover:text-text disabled:pointer-events-none disabled:opacity-35"
		{disabled}
		aria-label={label}
		title={label}
		onclick={() => goToPage(to)}
	>
		<Icon size={15} />
	</button>
{/snippet}

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
				{@render pagerBtn('First page', ChevronsLeft, pageNum === 1, 1)}
				{@render pagerBtn('Previous page', ChevronLeft, pageNum === 1, pageNum - 1)}
				<span class="px-2 font-mono text-xs text-muted" aria-current="page">
					{pageNum} / {totalPages}
				</span>
				{@render pagerBtn('Next page', ChevronRight, pageNum === totalPages, pageNum + 1)}
				{@render pagerBtn('Last page', ChevronsRight, pageNum === totalPages, totalPages)}
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
		onselect={() => selected.toggle(openId!, !selected.has(openId!), false)}
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
