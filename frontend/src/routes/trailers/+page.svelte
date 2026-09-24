<script lang="ts">
	import { SvelteSet } from 'svelte/reactivity';
	import {
		Clapperboard,
		CloudUpload,
		Crosshair,
		Download,
		FilterX,
		Film,
		Link as LinkIcon,
		Play,
		Search,
		Tag,
		Tags,
		Trash2,
		TriangleAlert,
		Upload,
		X
	} from '@lucide/svelte';
	import { onMount } from 'svelte';
	import { base } from '$app/paths';
	import { page } from '$app/state';
	import { ApiError, api, getCsrfToken, unwrap } from '$lib/api/client';
	import { query } from '$lib/api/query.svelte';
	import { liveRefresh } from '$lib/live.svelte';
	import { sortIndicator, toggleSort, type FilterControl, type SortSpec } from '$lib/filters';
	import { replaceState } from '$app/navigation';
	import { JobStream, unwrapLoose, type ApiJob, type JobEvent, jobIsActive } from '$lib/jobs';
	import { showToast } from '$lib/toast.svelte';
	import { invalidate } from '$lib/invalidate';
	import Badge from '$lib/components/ui/Badge.svelte';
	import StatusLamp from '$lib/components/StatusLamp.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Tabs from '$lib/components/ui/Tabs.svelte';
	import Dialog from '$lib/components/ui/Dialog.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import BulkBar from '$lib/components/BulkBar.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import FilterBar from '$lib/components/FilterBar.svelte';
	import JobProgress from '$lib/components/JobProgress.svelte';
	import DetailPanel from '$lib/components/DetailPanel.svelte';

	interface TrailerTag {
		id: number;
		name: string;
		trailer_count?: number;
	}

	interface Trailer {
		id: number;
		title: string;
		year: number | null;
		month: number | null;
		duration: number | null;
		content_rating: string | null;
		rating_ok: boolean;
		tmdbid: number | null;
		director: string | null;
		file_path: string | null;
		file_name: string;
		file_exists: boolean;
		stream_url: string;
		has_movie: boolean;
		genres: string[];
		trailer_tags: TrailerTag[];
		certificates?: Record<string, string>;
		rating_lookups?: Record<string, string>;
		associated_movie?: { id: number; title: string; year?: number | null } | null;
	}

	interface LibraryStats {
		total: number;
		with_file: number;
		missing: number;
		rating_issues: number;
	}

	interface LibraryFacets {
		ratings: string[];
		genres: string[];
		valid_ratings: string[];
		trailer_tags: TrailerTag[];
	}

	interface LibraryData {
		trailers: Trailer[];
		total: number;
		limit: number;
		offset: number;
		stats: LibraryStats;
		facets: LibraryFacets;
	}

	interface TmdbResult {
		tmdbid: number;
		title: string;
		year: number | null;
		poster_url: string | null;
		has_trailer: boolean;
		in_library: boolean;
	}

	const ISSUES = '__issues__';
	const LIMIT = 60;
	const DEFAULT_SORT = '-year';

	let q = $state('');
	let genre = $state('');
	let rating = $state('');
	let tag = $state('');
	let sort = $state(DEFAULT_SORT);
	let missing = $state(false);
	let year = $state<number | null>(null);

	let items = $state<Trailer[]>([]);
	let total = $state(0);
	let offset = $state(0);
	let stats = $state<LibraryStats | null>(null);
	let facets = $state<LibraryFacets | null>(null);
	let facetsLoaded = false;
	let loading = $state(true);
	let loadError = $state<ApiError | null>(null);
	let loadingMore = $state(false);

	let view = $state<'grid' | 'list'>(localStorage.getItem('tl_view') === 'list' ? 'list' : 'grid');
	// Declared here (not with the bulk code below): init reload() clears it; a later const would be in its TDZ.
	const selected = new SvelteSet<number>();

	const ratingIssue = $derived(rating === ISSUES);
	const filtersActive = $derived(Boolean(q || genre || rating || missing || year || tag));

	function buildParams() {
		const params: Record<string, string | number | boolean> = {
			limit: LIMIT,
			offset,
			sort
		};
		if (q) params.q = q;
		if (genre) params.genre = genre;
		if (rating && !ratingIssue) params.rating = rating;
		if (ratingIssue) params.rating_issue = true;
		if (year) params.year = year;
		if (tag) params.tag = Number(tag);
		if (missing) params.missing = true;
		return params;
	}

	let loadSeq = 0;
	async function loadLibrary(reset: boolean) {
		const seq = ++loadSeq;
		if (reset) {
			offset = 0;
			loading = true;
			loadError = null;
		} else {
			loadingMore = true;
		}
		try {
			const data = await unwrapLoose<LibraryData>(
				api.GET('/api/v2/trailers/library', {
					params: { query: buildParams() }
				})
			);
			if (seq !== loadSeq) return;
			total = data.total;
			stats = data.stats;
			if (reset) {
				items = data.trailers;
				if (!facetsLoaded) {
					facets = data.facets;
					facetsLoaded = true;
				} else if (facets) {
					facets.trailer_tags = data.facets.trailer_tags;
					facets.valid_ratings = data.facets.valid_ratings;
				}
			} else {
				items = [...items, ...data.trailers];
			}
			offset = items.length;
			loadError = null;
		} catch (e) {
			if (seq !== loadSeq) return;
			if (reset) loadError = e instanceof ApiError ? e : new ApiError(String(e), 0);
			else showToast(`Failed to load more: ${e instanceof Error ? e.message : e}`, 'error');
		} finally {
			if (seq === loadSeq) {
				loading = false;
				loadingMore = false;
			}
		}
	}

	function reload() {
		selected.clear();
		void loadLibrary(true);
	}

	async function refreshLibrary() {
		if (loading || loadingMore) return;
		const seq = ++loadSeq;
		try {
			const data = await unwrapLoose<LibraryData>(
				api.GET('/api/v2/trailers/library', {
					params: {
						query: { ...buildParams(), offset: 0, limit: Math.max(LIMIT, items.length) }
					}
				})
			);
			if (seq !== loadSeq) return;
			items = data.trailers;
			total = data.total;
			offset = items.length;
			stats = data.stats;
			if (facets) {
				facets.trailer_tags = data.facets.trailer_tags;
				facets.valid_ratings = data.facets.valid_ratings;
			}
			loadError = null;
		} catch {
			/* background refresh — keep what's on screen */
		}
	}

	$effect(() => liveRefresh(() => void refreshLibrary()));

	function clearFilters() {
		q = '';
		genre = '';
		rating = '';
		tag = '';
		missing = false;
		year = null;
		reload();
	}

	function resetFilters() {
		sort = DEFAULT_SORT;
		clearFilters();
	}

	const deepQ = page.url.searchParams.get('q');
	if (deepQ) q = deepQ;
	const deepTrailer = page.url.searchParams.get('trailer');

	reload();

	// openDetail writes selectedId, declared further down — calling it during script init would hit its TDZ.
	onMount(() => {
		if (deepTrailer && /^\d+$/.test(deepTrailer)) void openDetail(Number(deepTrailer));
	});

	$effect(() => {
		if (page.url.searchParams.get('fetch') !== 'open') return;
		openFetchDialog();
		const url = new URL(page.url);
		url.searchParams.delete('fetch');
		replaceState(url, {});
	});

	const countText = $derived(
		offset < total
			? `Showing ${offset} of ${total} trailers`
			: `${total} trailer${total === 1 ? '' : 's'}`
	);

	const filterControls = $derived<FilterControl[]>([
		{
			id: 'genre',
			label: 'Genre',
			allLabel: 'All genres',
			value: genre,
			options: (facets?.genres ?? []).map((g) => ({ value: g, label: g })),
			onchange: (v) => {
				genre = v;
				reload();
			}
		},
		{
			id: 'rating',
			label: 'Rating',
			allLabel: 'All ratings',
			value: rating,
			options: [
				...(facets?.ratings ?? []).map((r) => ({ value: r, label: r })),
				{ value: ISSUES, label: 'Rating problems', count: stats?.rating_issues || undefined }
			],
			onchange: (v) => {
				rating = v;
				reload();
			}
		},
		...(facets?.trailer_tags.length
			? ([
					{
						id: 'tag',
						label: 'Tag',
						allLabel: 'All tags',
						value: tag,
						options: facets.trailer_tags.map((t) => ({
							value: String(t.id),
							label: t.name,
							count: t.trailer_count
						})),
						onchange: (v: string) => {
							tag = v;
							reload();
						}
					}
				] as FilterControl[])
			: []),
		{
			id: 'year',
			label: 'Year',
			allLabel: '',
			value: year ? String(year) : '',
			options: [],
			chipOnly: true,
			onchange: (v) => {
				year = v ? Number(v) : null;
				reload();
			}
		},
		{
			kind: 'toggle',
			id: 'missing',
			label: 'Missing file',
			value: missing,
			onchange: (v) => {
				missing = v;
				reload();
			}
		}
	]);

	const sortSpec = $derived<SortSpec>({
		value: sort,
		options: [
			{ value: '-year', label: 'Newest first' },
			{ value: 'year', label: 'Oldest first' },
			{ value: 'title', label: 'Title A-Z' },
			{ value: '-title', label: 'Title Z-A' },
			{ value: 'content_rating', label: 'Rating (low-high)' },
			{ value: '-content_rating', label: 'Rating (high-low)' }
		],
		default: DEFAULT_SORT,
		onchange: (v) => {
			sort = v;
			reload();
		}
	});

	const ratingsOptions = query(() => unwrap(api.GET('/api/v2/movies/ratings-options')));
	const ratingsSystem = $derived(ratingsOptions.data?.system ?? 'BBFC');

	function certOptions(current: string | null): { value: string; label: string }[] {
		const ordered = ratingsOptions.data?.ratings?.length
			? ratingsOptions.data.ratings
			: (facets?.valid_ratings ?? []);
		const opts: { value: string; label: string }[] = [{ value: '', label: '- none -' }];
		if (current && !ordered.includes(current)) {
			opts.push({ value: current, label: `${current} (not ${ratingsSystem})` });
		}
		for (const r of ordered) opts.push({ value: r, label: r });
		return opts;
	}

	function filterYear(y: number) {
		year = y;
		closeDetail();
		reload();
	}
	function filterGenre(g: string) {
		genre = g;
		closeDetail();
		reload();
	}
	function filterDirector(d: string) {
		q = d;
		closeDetail();
		reload();
	}
	function filterRating(r: string) {
		rating = r;
		closeDetail();
		reload();
	}
	function filterTag(id: number) {
		tag = String(id);
		closeDetail();
		reload();
	}

	const allSelected = $derived(items.length > 0 && items.every((t) => selected.has(t.id)));

	function toggleAll(on: boolean) {
		if (on) items.forEach((t) => selected.add(t.id));
		else selected.clear();
	}

	let confirmDialog: ConfirmDialog;

	async function bulkDeleteSelected() {
		const ids = [...selected];
		if (!ids.length) return;
		const ok = await confirmDialog.confirm(
			`Remove ${ids.length} trailer${ids.length === 1 ? '' : 's'} from the library? This deletes the records AND the files on disk.`
		);
		if (!ok) return;
		try {
			const res = await unwrapLoose<{ deleted: number; file_errors?: string[] }>(
				api.POST('/api/v2/trailers/library/bulk-delete', {
					body: { ids, delete_files: true }
				})
			);
			selected.clear();
			items = items.filter((x) => !ids.includes(x.id));
			total -= res.deleted;
			const errs = res.file_errors?.length
				? ` (${res.file_errors.length} file${res.file_errors.length === 1 ? '' : 's'} could not be removed)`
				: '';
			showToast(
				`Removed ${res.deleted} trailer${res.deleted === 1 ? '' : 's'}${errs}`,
				errs ? 'warning' : 'success'
			);
			void refreshLibrary();
			invalidate('trailers');
		} catch (e) {
			showToast(`Bulk delete failed: ${e instanceof Error ? e.message : e}`, 'error');
		}
	}

	let bulkTagOpen = $state(false);
	let bulkTagName = $state('');
	let bulkTagBusy = $state(false);

	function openBulkTag() {
		if (!selected.size) return;
		bulkTagName = '';
		bulkTagOpen = true;
	}

	async function applyBulkTag() {
		const name = bulkTagName.trim();
		if (!name) {
			showToast('Enter a tag name', 'error');
			return;
		}
		bulkTagBusy = true;
		try {
			const res = await unwrapLoose<{ tagged: number; tag: TrailerTag }>(
				api.POST('/api/v2/trailers/library/bulk-tag', {
					body: { ids: [...selected], name }
				})
			);
			bulkTagOpen = false;
			showToast(
				`Tagged ${res.tagged} trailer${res.tagged === 1 ? '' : 's'} with "${res.tag.name}"`,
				'success'
			);
			selected.clear();
			void refreshLibrary();
		} catch (e) {
			showToast(`Tagging failed: ${e instanceof Error ? e.message : e}`, 'error');
		} finally {
			bulkTagBusy = false;
		}
	}

	const sortCols: { key: string; label: string; defaultDesc?: boolean }[] = [
		{ key: 'title', label: 'Title' },
		{ key: 'year', label: 'Year', defaultDesc: true },
		{ key: 'content_rating', label: 'Cert' }
	];

	function headerSort(key: string, defaultDesc?: boolean) {
		sort = toggleSort(sort, key, defaultDesc);
		reload();
	}

	let selectedId = $state<number | null>(null);
	let detail = $state<Trailer | null>(null);
	let detailLoading = $state(false);
	let detailError = $state<string | null>(null);

	async function openDetail(id: number) {
		selectedId = id;
		detail = null;
		detailError = null;
		detailLoading = true;
		try {
			const data = await unwrapLoose<{ trailer: Trailer }>(
				api.GET('/api/v2/trailers/library/{trailer_id}', {
					params: { path: { trailer_id: id } }
				})
			);
			if (selectedId !== id) return;
			detail = data.trailer;
		} catch (e) {
			if (selectedId !== id) return;
			detailError = e instanceof Error ? e.message : 'Failed to load trailer';
		} finally {
			if (selectedId === id) detailLoading = false;
		}
	}

	function closeDetail() {
		selectedId = null;
		detail = null;
	}

	function onWindowKeydown(e: KeyboardEvent) {
		// Native <dialog>s own Escape while open.
		if (e.key === 'Escape' && !document.querySelector('dialog[open]')) closeDetail();
	}

	const knownTags = $derived(facets?.trailer_tags ?? []);

	function syncItemTags(id: number, tags: TrailerTag[]) {
		const item = items.find((x) => x.id === id);
		if (item) item.trailer_tags = tags;
	}

	function refreshTagFacet() {
		unwrapLoose<{ tags: TrailerTag[] }>(api.GET('/api/v2/trailers/tags'))
			.then((res) => {
				if (facets) facets.trailer_tags = res.tags ?? [];
			})
			.catch(() => {
				/* facet refresh is cosmetic */
			});
	}

	let detailTagInput = $state('');

	async function detailAddTag(t: Trailer) {
		const name = detailTagInput.trim();
		if (!name) return;
		try {
			const res = await unwrapLoose<{ trailer_tags: TrailerTag[] }>(
				api.POST('/api/v2/trailers/library/{trailer_id}/tags', {
					params: { path: { trailer_id: t.id } },
					body: { name }
				})
			);
			t.trailer_tags = res.trailer_tags;
			syncItemTags(t.id, res.trailer_tags);
			detailTagInput = '';
			void refreshLibrary();
		} catch (e) {
			showToast(`Could not add tag: ${e instanceof Error ? e.message : e}`, 'error');
		}
	}

	async function detailRemoveTag(t: Trailer, tagId: number) {
		try {
			const res = await unwrapLoose<{ trailer_tags: TrailerTag[] }>(
				api.DELETE('/api/v2/trailers/library/{trailer_id}/tags/{tag_id}', {
					params: { path: { trailer_id: t.id, tag_id: tagId } }
				})
			);
			t.trailer_tags = res.trailer_tags;
			syncItemTags(t.id, res.trailer_tags);
			void refreshLibrary();
		} catch (e) {
			showToast(`Could not remove tag: ${e instanceof Error ? e.message : e}`, 'error');
		}
	}

	async function updateRating(id: number, value: string) {
		try {
			const data = await unwrapLoose<{ trailer: Trailer }>(
				api.PATCH('/api/v2/trailers/library/{trailer_id}', {
					params: { path: { trailer_id: id } },
					body: { content_rating: value }
				})
			);
			const updated = data.trailer;
			const i = items.findIndex((x) => x.id === id);
			if (i >= 0) items[i] = updated;
			if (ratingIssue && updated.rating_ok) {
				items = items.filter((x) => x.id !== id);
				total = Math.max(0, total - 1);
				closeDetail();
			} else if (detail?.id === id) {
				detail = updated;
			}
			showToast('Certification updated', 'success');
			void refreshLibrary();
		} catch (e) {
			showToast(`Update failed: ${e instanceof Error ? e.message : e}`, 'error');
		}
	}

	let playOpen = $state(false);
	let playing = $state<Trailer | null>(null);

	function playTrailer(t: Trailer | undefined | null) {
		if (!t || !t.file_exists) {
			showToast('File is missing on disk', 'error');
			return;
		}
		playing = t;
		playOpen = true;
	}
	$effect(() => {
		if (!playOpen) playing = null;
	});

	async function deleteTrailer(t: Trailer, fromDetail = false) {
		const ok = await confirmDialog.confirm(
			`Remove "${t.title}" from the library? This deletes the record AND the file on disk.`
		);
		if (!ok) return;
		try {
			await unwrapLoose(
				api.DELETE('/api/v2/trailers/library/{trailer_id}', {
					params: { path: { trailer_id: t.id }, query: { delete_file: true } }
				})
			);
			items = items.filter((x) => x.id !== t.id);
			total -= 1;
			selected.delete(t.id);
			if (fromDetail) closeDetail();
			showToast('Trailer removed', 'success');
			void refreshLibrary();
			invalidate('trailers');
		} catch (e) {
			showToast(`Delete failed: ${e instanceof Error ? e.message : e}`, 'error');
		}
	}

	const OP_LABEL: Record<string, string> = {
		discover: 'Discover trailers',
		upcoming: 'Discover trailers',
		single: 'Fetch trailer',
		library: 'Fetch library trailers',
		verify: 'Verify trailer directory',
		ratings: 'Update certificate ratings',
		rename: 'Rename trailers'
	};

	let trailerJob = $state<ApiJob | null>(null);
	let jobActive = $state(false);

	$effect(() => {
		void reattachJob();
	});

	$effect(() => {
		const stream = new JobStream(
			{ kind: 'trailer' },
			{
				onState: onJobEvent,
				onProgress: onJobEvent,
				onComplete: (p) => {
					if (!jobActive && trailerJob && p.job_id !== trailerJob.id) return;
					onJobComplete(p);
				},
				onOpen: () => void reattachJob()
			}
		);
		stream.open();
		return () => stream.close();
	});

	async function reattachJob() {
		try {
			const data = await unwrapLoose<{ job: ApiJob | null }>(
				api.GET('/api/v2/trailers/jobs/current')
			);
			if (data.job) {
				trailerJob = data.job;
				jobActive = data.job.is_active;
			}
		} catch {
			/* no current job */
		}
	}

	function onJobEvent(p: JobEvent) {
		jobActive = jobIsActive(p.state);
		if (jobIsActive(p.state) && (!trailerJob || trailerJob.id !== p.job_id)) void reattachJob();
	}

	function onJobComplete(p: JobEvent) {
		jobActive = false;
		const parts = Object.entries(p.counts ?? {})
			.filter(([, v]) => typeof v === 'number' && v)
			.map(([k, v]) => `${k}: ${v}`);
		const summary = p.error
			? `${OP_LABEL[p.operation] || 'Job'} ${p.state}: ${String(p.error).split('\n')[0]}`
			: `${OP_LABEL[p.operation] || 'Job'} ${p.state}${parts.length ? ' - ' + parts.join(', ') : ''}`;
		showToast(summary, p.state === 'success' ? 'success' : p.state === 'failed' ? 'error' : 'info');
		void refreshLibrary();
		invalidate('trailers');
		if (sResults?.length) void runTitleSearch();
		if (selectedId !== null) void openDetail(selectedId);
	}

	async function startJob(
		run: () => PromiseLike<{ data?: unknown; error?: unknown; response: Response }>
	) {
		try {
			const data = await unwrapLoose<{ job: ApiJob }>(run());
			trailerJob = data.job;
			jobActive = true;
			showToast('Job started', 'success');
		} catch (e) {
			const msg = e instanceof Error ? e.message : String(e);
			if (/already running/i.test(msg)) {
				showToast('A trailer job is already running', 'info');
				await reattachJob();
			} else {
				showToast(`Failed: ${msg}`, 'error');
			}
		}
	}

	let fetchOpen = $state(false);
	const FETCH_TABS = [
		{ id: 'search', label: 'Search' },
		{ id: 'discover', label: 'Discover' },
		{ id: 'upload', label: 'Upload' },
		{ id: 'library', label: 'Library' },
		{ id: 'verify', label: 'Verify' },
		{ id: 'ratings', label: 'Ratings' }
	];
	let fetchTab = $state<'search' | 'discover' | 'upload' | 'library' | 'verify' | 'ratings'>(
		'search'
	);
	let keyMissing = $state(false);

	let fYearFrom = $state('');
	let fYearTo = $state('');
	let fLimit = $state('50');
	let fSort = $state('popularity.desc');
	let fMinRating = $state('');
	let fCert = $state('');

	function openFetchDialog() {
		fetchOpen = true;
		void reattachJob();
		unwrapLoose<{ settings: { tmdb_api_key?: string } }>(api.GET('/api/v2/trailers/settings'))
			.then((data) => {
				keyMissing = !(data.settings?.tmdb_api_key || '').trim();
			})
			.catch(() => {
				/* leave the notice hidden */
			});
	}

	let sQuery = $state('');
	let sResults = $state<TmdbResult[] | null>(null);
	let sSearching = $state(false);
	let sNoKey = $state(false);
	let sTimer: ReturnType<typeof setTimeout> | undefined;

	async function runTitleSearch() {
		const term = sQuery.trim();
		if (term.length < 2) {
			sResults = null;
			return;
		}
		sSearching = true;
		try {
			const res = await unwrapLoose<{ results: TmdbResult[]; api_key_configured: boolean }>(
				api.GET('/api/v2/trailers/tmdb-search', { params: { query: { q: term, limit: 10 } } })
			);
			sNoKey = !res.api_key_configured;
			sResults = res.results;
		} catch (e) {
			sResults = null;
			showToast(`Search failed: ${e instanceof Error ? e.message : e}`, 'error');
		} finally {
			sSearching = false;
		}
	}

	function onTitleSearchInput() {
		clearTimeout(sTimer);
		sTimer = setTimeout(() => void runTitleSearch(), 300);
	}

	function fetchSingle(r: TmdbResult) {
		void startJob(() =>
			api.POST('/api/v2/trailers/fetch', {
				// limit/sort_by/months_ahead carry schema defaults the backend ignores for a single-title fetch.
				body: {
					type: 'single',
					tmdbid: r.tmdbid,
					replace: false,
					months_ahead: 6,
					limit: 50,
					sort_by: 'popularity.desc'
				}
			})
		);
	}

	interface TmdbVideo {
		key: string;
		name: string;
		type: string;
		size: number | null;
		official: boolean;
		published_at: string;
	}
	let vpOpen = $state(false);
	let vpTitle = $state('');
	let vpTmdbid = $state(0);
	let vpReplace = $state(false);
	let vpVideos = $state<TmdbVideo[] | null>(null);
	let vpError = $state<string | null>(null);

	async function openVideoPicker(tmdbid: number, title: string, replace: boolean) {
		vpTmdbid = tmdbid;
		vpTitle = title;
		vpReplace = replace;
		vpVideos = null;
		vpError = null;
		vpOpen = true;
		try {
			const data = await unwrapLoose<{ videos: TmdbVideo[] }>(
				api.GET('/api/v2/trailers/tmdb-videos', { params: { query: { tmdbid } } })
			);
			vpVideos = data.videos;
		} catch (e) {
			vpError = e instanceof Error ? e.message : String(e);
		}
	}

	function fetchVideo(v: TmdbVideo) {
		vpOpen = false;
		void startJob(() =>
			api.POST('/api/v2/trailers/fetch', {
				body: {
					type: 'single',
					tmdbid: vpTmdbid,
					video_key: v.key,
					replace: vpReplace,
					months_ahead: 6,
					limit: 50,
					sort_by: 'popularity.desc'
				}
			})
		);
	}

	function buildFetchParams() {
		const p: {
			year_from?: number;
			year_to?: number;
			limit: number;
			sort_by: string;
			min_rating?: number;
			certification?: string;
		} = { sort_by: fSort, limit: parseInt(fLimit, 10) || 50 };
		if (fYearFrom) p.year_from = parseInt(fYearFrom, 10);
		if (fYearTo) p.year_to = parseInt(fYearTo, 10);
		if (fMinRating) p.min_rating = parseFloat(fMinRating);
		if (fCert) p.certification = fCert;
		return p;
	}

	type Preview = {
		trailers: {
			title: string;
			year: number | null;
			genres: string[];
			rating: number | null;
			already_downloaded: boolean;
		}[];
		total_found: number;
		will_fetch: number;
		already_have: number;
	};
	let preview = $state<Preview | null>(null);
	let previewMsg = $state<string | null>(null);

	async function runPreview() {
		preview = null;
		previewMsg = 'Querying TMDB…';
		try {
			preview = (await unwrap(
				api.POST('/api/v2/trailers/preview', { body: buildFetchParams() })
			)) as Preview;
			previewMsg = null;
		} catch (e) {
			previewMsg = `Preview failed: ${e instanceof Error ? e.message : e}`;
		}
	}

	function runFetch(type: 'discover' | 'library') {
		// months_ahead/limit/sort_by carry schema defaults the backend ignores for a plain library fetch.
		const base = { type, months_ahead: 6, replace: false };
		const body =
			type === 'discover'
				? { ...base, ...buildFetchParams() }
				: { ...base, limit: 50, sort_by: 'popularity.desc' };
		void startJob(() => api.POST('/api/v2/trailers/fetch', { body }));
	}

	function runVerify() {
		void startJob(() => api.POST('/api/v2/trailers/verify'));
	}

	function runRatings() {
		void startJob(() =>
			api.POST('/api/v2/trailers/ratings/update', { body: { scope: 'trailers' } })
		);
	}

	interface RenameChange {
		action: string;
		label: string;
		detail: string;
	}
	let renameOpen = $state(false);
	let renamePlan = $state<{ total: number; changes: RenameChange[] } | null>(null);
	let renameMsg = $state<string | null>(null);
	let renameBusy = $state(false);

	async function openRename() {
		renamePlan = null;
		renameMsg = 'Computing preview…';
		renameOpen = true;
		try {
			const res = await unwrapLoose<{ plan: { total: number; changes: RenameChange[] } }>(
				api.POST('/api/v2/trailers/library/rename', {
					params: { query: { dry_run: true } }
				})
			);
			renamePlan = res.plan;
			renameMsg = null;
		} catch (e) {
			renameMsg = `Failed: ${e instanceof Error ? e.message : e}`;
		}
	}

	const renameChanges = $derived((renamePlan?.changes ?? []).filter((c) => c.action === 'update'));
	const renameConflicts = $derived(
		(renamePlan?.changes ?? []).filter((c) => c.action === 'conflict')
	);

	async function applyRename() {
		renameBusy = true;
		try {
			const res = await unwrapLoose<{ counts: Record<string, number> }>(
				api.POST('/api/v2/trailers/library/rename', {
					params: { query: { dry_run: false } }
				})
			);
			showToast(`Renamed ${res.counts?.renamed || 0} file(s)`, 'success');
			renameOpen = false;
			void refreshLibrary();
		} catch (e) {
			showToast(`Rename failed: ${e instanceof Error ? e.message : e}`, 'error');
		} finally {
			renameBusy = false;
		}
	}

	let matchOpen = $state(false);
	let matchSearch = $state('');
	let matchResults = $state<{ id: number; title: string; year: number | null }[]>([]);
	type MatchData = {
		movie_title: string | null;
		matched: number;
		requested: number;
		trailers: {
			id: number;
			title: string;
			year: number | null;
			content_rating: string;
			will_play: boolean;
		}[];
	};
	let matchData = $state<MatchData | null>(null);
	let matchMsg = $state<string | null>(null);
	let matchTimer: ReturnType<typeof setTimeout> | undefined;

	function openMatchTest() {
		matchOpen = true;
	}

	function onMatchSearchInput() {
		clearTimeout(matchTimer);
		matchTimer = setTimeout(async () => {
			const term = matchSearch.trim();
			if (term.length < 2) {
				matchResults = [];
				return;
			}
			try {
				const data = await unwrap(
					api.GET('/api/v2/movies/list', {
						params: { query: { search: term, per_page: 8 } }
					})
				);
				matchResults = data.items.map((m) => ({ id: m.id, title: m.title, year: m.year ?? null }));
			} catch {
				matchResults = [];
			}
		}, 250);
	}

	async function runMatchTest(movieId: number) {
		matchResults = [];
		matchSearch = '';
		matchData = null;
		matchMsg = 'Matching…';
		try {
			matchData = (await unwrap(
				api.GET('/api/v2/trailers/match-test', {
					params: { query: { movie_id: movieId } }
				})
			)) as MatchData;
			matchMsg = null;
		} catch {
			matchMsg = 'Could not run the match test.';
		}
	}

	let upFile = $state<File | null>(null);
	let upTitle = $state('');
	let upTmdb = $state<TmdbResult | null>(null);
	let upTmdbSearch = $state('');
	let upTmdbResults = $state<TmdbResult[] | null>(null);
	let upTmdbNoKey = $state(false);
	let upTagNames = $state<string[]>([]);
	let upTagInput = $state('');
	let upBusy = $state(false);
	let upPct = $state(0);
	let upDragOver = $state(false);
	let upFileInput = $state<HTMLInputElement | undefined>();
	let upTmdbTimer: ReturnType<typeof setTimeout> | undefined;

	function resetUploadForm() {
		upFile = null;
		upTitle = '';
		upTmdb = null;
		upTmdbSearch = '';
		upTmdbResults = null;
		upTmdbNoKey = false;
		upTagNames = [];
		upTagInput = '';
		upBusy = false;
		upPct = 0;
		refreshTagFacet();
	}

	function setUploadFile(f: File) {
		upFile = f;
		if (!upTitle.trim() && !upTmdb) upTitle = f.name.replace(/\.[^.]+$/, '');
	}

	function onUploadDrop(e: DragEvent) {
		e.preventDefault();
		upDragOver = false;
		const f = e.dataTransfer?.files?.[0];
		if (f) setUploadFile(f);
	}

	function onTmdbSearchInput() {
		clearTimeout(upTmdbTimer);
		upTmdbTimer = setTimeout(async () => {
			const term = upTmdbSearch.trim();
			if (term.length < 2) {
				upTmdbResults = null;
				return;
			}
			try {
				const res = await unwrapLoose<{ results: TmdbResult[]; api_key_configured: boolean }>(
					api.GET('/api/v2/trailers/tmdb-search', { params: { query: { q: term } } })
				);
				upTmdbNoKey = !res.api_key_configured;
				upTmdbResults = res.results;
			} catch {
				upTmdbResults = null;
			}
		}, 300);
	}

	function selectTmdb(r: TmdbResult) {
		upTmdb = r;
		upTmdbSearch = '';
		upTmdbResults = null;
		upTitle = r.title;
	}

	function toggleUploadTag(name: string) {
		upTagNames = upTagNames.includes(name)
			? upTagNames.filter((n) => n !== name)
			: [...upTagNames, name];
	}

	function addUploadTag() {
		const name = upTagInput.trim();
		if (!name) return;
		if (!upTagNames.includes(name)) upTagNames = [...upTagNames, name];
		upTagInput = '';
	}

	const uploadTagChoices = $derived([...new Set([...knownTags.map((t) => t.name), ...upTagNames])]);

	// XHR because fetch has no upload progress; CSRF/credentials match client.ts.
	function uploadTrailerFile(
		file: File,
		fields: Record<string, string>,
		onProgress: (pct: number) => void
	): Promise<void> {
		return new Promise((resolve, reject) => {
			const fd = new FormData();
			fd.append('file', file);
			for (const [k, v] of Object.entries(fields)) fd.append(k, v);
			const xhr = new XMLHttpRequest();
			xhr.open('POST', '/api/v2/trailers/upload');
			xhr.withCredentials = true;
			xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
			const token = getCsrfToken();
			if (token) xhr.setRequestHeader('X-CSRFToken', token);
			xhr.upload.onprogress = (e) => {
				if (e.lengthComputable) onProgress((e.loaded / e.total) * 100);
			};
			xhr.onload = () => {
				if (xhr.status >= 200 && xhr.status < 300) {
					resolve();
					return;
				}
				let message = `Upload failed (${xhr.status})`;
				try {
					const env = JSON.parse(xhr.responseText) as { error?: string; message?: string };
					message = env.error || env.message || message;
				} catch {
					/* non-JSON error body */
				}
				reject(new ApiError(message, xhr.status));
			};
			xhr.onerror = () => reject(new ApiError('Upload failed (network)', 0));
			xhr.send(fd);
		});
	}

	async function submitUpload() {
		if (upBusy) return;
		if (!upFile) {
			showToast('Choose a trailer file first', 'error');
			return;
		}
		const title = upTitle.trim();
		if (!upTmdb && !title) {
			showToast('Enter a title or link a TMDB movie', 'error');
			return;
		}
		const fields: Record<string, string> = {};
		if (title) fields.title = title;
		if (upTmdb) fields.tmdbid = String(upTmdb.tmdbid);
		if (upTagNames.length) fields.tags = upTagNames.join(',');

		upBusy = true;
		upPct = 0;
		try {
			await uploadTrailerFile(upFile, fields, (pct) => (upPct = pct));
			showToast(`Trailer "${title || upTmdb!.title}" uploaded`, 'success');
			fetchOpen = false;
			void refreshLibrary();
			invalidate('trailers');
		} catch (e) {
			showToast(`Upload failed: ${e instanceof Error ? e.message : e}`, 'error');
		} finally {
			upBusy = false;
		}
	}
</script>

<svelte:head><title>Trailers - Cinefin</title></svelte:head>
<svelte:window onkeydown={onWindowKeydown} />

<ConfirmDialog bind:this={confirmDialog} confirmLabel="Delete" />

<div class="mb-3 flex flex-wrap items-center gap-2">
	<h1 class="mr-auto text-lg font-semibold">Trailer library</h1>
	<Button onclick={openMatchTest} title="See which trailers a trailer rule would pick for a movie">
		<Crosshair size={14} /> Test matching…
	</Button>
	<Button onclick={openRename} title="Rename trailer files to the naming scheme">
		<Tag size={14} /> Rename to scheme…
	</Button>
	<Button
		variant="primary"
		onclick={openFetchDialog}
		title="Search, discover, upload or verify trailers"
	>
		<Download size={14} /> Get trailers…
	</Button>
</div>

{#if stats}
	<p class="mb-3 flex flex-wrap gap-x-3 font-mono text-xs text-muted">
		<span>{stats.total} total</span>
		<span class="text-success">{stats.with_file} on disk</span>
		{#if stats.missing}<span class="text-warning">{stats.missing} missing file</span>{/if}
		{#if stats.rating_issues}<span class="text-warning">{stats.rating_issues} rating issues</span
			>{/if}
	</p>
{/if}

<FilterBar
	search={{
		value: q,
		placeholder: 'Search title or director…',
		debounce: 250,
		onchange: (v) => {
			q = v;
			reload();
		}
	}}
	filters={filterControls}
	sort={sortSpec}
	count={countText}
	bind:view
	viewKey="tl_view"
	onreset={resetFilters}
/>

<div class="flex items-start gap-4">
	<div class="min-w-0 flex-1">
		{#if loading}
			<Spinner label="Loading trailers…" />
		{:else if loadError}
			<ErrorState error={loadError} retry={() => void loadLibrary(true)} />
		{:else if !items.length}
			{#if filtersActive}
				<EmptyState
					icon={FilterX}
					title="No trailers match these filters"
					message="No trailers match your current search or filters. Try broadening them, or clear the filters to see the whole library."
				>
					{#snippet action()}
						<Button onclick={clearFilters}>Clear filters</Button>
					{/snippet}
				</EmptyState>
			{:else}
				<EmptyState
					icon={Clapperboard}
					title="No trailers yet"
					message="Your trailer library is empty. Discover trailers on TMDB or fetch them for the movies already in your library."
				>
					{#snippet action()}
						<Button variant="primary" onclick={openFetchDialog}>
							<Download size={14} /> Get trailers
						</Button>
					{/snippet}
				</EmptyState>
			{/if}
		{:else if view === 'grid'}
			<!-- Auto-fill, not breakpoints: the detail drawer takes width from this grid when docked. -->
			<div class="grid grid-cols-[repeat(auto-fill,minmax(15rem,1fr))] gap-3">
				{#each items as t (t.id)}
					<div
						class="group cursor-pointer rounded-md border border-border bg-surface-1 p-3 transition-colors
							hover:border-border-strong {t.file_exists ? '' : 'opacity-75'}"
						data-panel-item={t.id}
						data-panel-current={t.id === selectedId || undefined}
						role="button"
						tabindex="0"
						onclick={() => openDetail(t.id)}
						onkeydown={(e) => {
							if (e.key === 'Enter' || e.key === ' ') {
								e.preventDefault();
								openDetail(t.id);
							}
						}}
					>
						<div class="mb-2 flex items-center justify-between gap-2">
							<button
								type="button"
								class="rounded-md border border-border-strong bg-surface-2 p-1.5 text-muted
									hover:text-accent disabled:opacity-40"
								title="Play"
								disabled={!t.file_exists}
								onclick={(e) => {
									e.stopPropagation();
									playTrailer(t);
								}}
							>
								<Play size={13} />
							</button>
							<button
								type="button"
								class="font-mono text-xs {t.content_rating
									? t.rating_ok
										? 'text-muted hover:text-accent'
										: 'text-warning'
									: 'text-warning'}"
								title={!t.content_rating
									? 'No rating'
									: t.rating_ok
										? 'Show this rating only'
										: 'Rating not in configured set - click to show'}
								onclick={(e) => {
									e.stopPropagation();
									if (t.content_rating) filterRating(t.content_rating);
								}}
							>
								{#if t.content_rating}
									{t.content_rating}{t.rating_ok ? '' : ' !'}
								{:else}
									no rating
								{/if}
							</button>
						</div>
						<p class="truncate text-sm font-medium group-hover:text-accent" title={t.title}>
							{t.title}
						</p>
						<p class="truncate text-xs text-muted">
							{#if t.year}
								<button
									type="button"
									class="hover:text-accent"
									title="Show {t.year} trailers"
									onclick={(e) => {
										e.stopPropagation();
										filterYear(t.year!);
									}}>{t.year}</button
								>
							{/if}
							{#if t.director}
								{t.year ? ' · ' : ''}<button
									type="button"
									class="hover:text-accent"
									title="Show trailers by {t.director}"
									onclick={(e) => {
										e.stopPropagation();
										filterDirector(t.director!);
									}}>{t.director}</button
								>
							{/if}
						</p>
						<p class="truncate text-xs text-faint">
							{#each (t.genres ?? []).slice(0, 3) as g, i (g)}
								{i ? ' · ' : ''}<button
									type="button"
									class="hover:text-accent"
									title="Show {g} trailers"
									onclick={(e) => {
										e.stopPropagation();
										filterGenre(g);
									}}>{g}</button
								>
							{/each}
						</p>
						{#if t.trailer_tags?.length}
							<p class="mt-1 flex flex-wrap gap-1">
								{#each t.trailer_tags as tg (tg.id)}
									<button
										type="button"
										class="inline-flex items-center gap-1 rounded-sm bg-surface-3 px-1.5 py-0.5
											text-[10px] text-muted hover:text-accent"
										title="Show trailers tagged {tg.name}"
										onclick={(e) => {
											e.stopPropagation();
											filterTag(tg.id);
										}}
									>
										<Tag size={9} />{tg.name}
									</button>
								{/each}
							</p>
						{/if}
						<div class="mt-2 flex items-center justify-between">
							{#if t.file_exists}
								<StatusLamp colour="green" quiet>On disk</StatusLamp>
							{:else}
								<StatusLamp colour="amber">Missing</StatusLamp>
							{/if}
							<button
								type="button"
								class="rounded-sm p-1 text-faint hover:text-danger"
								title="Remove"
								aria-label="Delete"
								onclick={(e) => {
									e.stopPropagation();
									void deleteTrailer(t);
								}}
							>
								<Trash2 size={13} />
							</button>
						</div>
					</div>
				{/each}
			</div>
		{:else}
			<BulkBar count={selected.size} onclear={() => selected.clear()}>
				<Button size="sm" onclick={openBulkTag}><Tags size={13} /> Tag selected</Button>
				<Button size="sm" variant="danger" onclick={bulkDeleteSelected}>
					<Trash2 size={13} /> Delete selected
				</Button>
			</BulkBar>
			<div class="overflow-x-auto border border-border">
				<table class="w-full text-sm">
					<thead>
						<tr
							class="border-b border-border bg-surface-2 text-left text-xs font-medium text-muted"
						>
							<th class="w-8 px-3 py-2">
								<input
									type="checkbox"
									aria-label="Select all"
									class="accent-accent"
									checked={allSelected}
									onchange={(e) => toggleAll((e.currentTarget as HTMLInputElement).checked)}
								/>
							</th>
							<th class="w-9 px-3 py-2"></th>
							{#each sortCols as col (col.key)}
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
							<th class="px-3 py-2">Genres</th>
							<th class="px-3 py-2">File</th>
							<th class="w-9 px-3 py-2"></th>
						</tr>
					</thead>
					<tbody class="divide-y divide-border">
						{#each items as t (t.id)}
							<tr
								class="cursor-pointer hover:bg-surface-2"
								data-panel-item={t.id}
								data-panel-current={t.id === selectedId || undefined}
								onclick={() => openDetail(t.id)}
							>
								<td class="px-3 py-1.5">
									<input
										type="checkbox"
										aria-label="Select trailer"
										class="accent-accent"
										checked={selected.has(t.id)}
										onclick={(e) => e.stopPropagation()}
										onchange={(e) => {
											if ((e.currentTarget as HTMLInputElement).checked) selected.add(t.id);
											else selected.delete(t.id);
										}}
									/>
								</td>
								<td class="px-3 py-1.5">
									<button
										type="button"
										class="rounded-sm p-1 text-muted hover:text-accent disabled:opacity-40"
										title="Play"
										disabled={!t.file_exists}
										onclick={(e) => {
											e.stopPropagation();
											playTrailer(t);
										}}
									>
										<Play size={13} />
									</button>
								</td>
								<td class="max-w-64 truncate px-3 py-1.5">{t.title}</td>
								<td class="px-3 py-1.5 font-mono text-xs">{t.year ?? ''}</td>
								<td class="px-3 py-1.5 font-mono text-xs">
									{#if t.content_rating}
										<span class={t.rating_ok ? '' : 'text-warning'}>
											{t.content_rating}{t.rating_ok ? '' : ' !'}
										</span>
									{:else}
										<span class="text-warning">-</span>
									{/if}
								</td>
								<td class="max-w-56 truncate px-3 py-1.5 text-xs text-muted">
									{(t.genres ?? []).join(', ')}
									{#if t.trailer_tags?.length}
										<span class="text-faint">
											[{t.trailer_tags.map((tg) => tg.name).join(', ')}]
										</span>
									{/if}
								</td>
								<td class="px-3 py-1.5">
									{#if t.file_exists}
										<StatusLamp colour="green" quiet>On disk</StatusLamp>
									{:else}
										<StatusLamp colour="amber">Missing</StatusLamp>
									{/if}
								</td>
								<td class="px-3 py-1.5">
									<button
										type="button"
										class="rounded-sm p-1 text-faint hover:text-danger"
										title="Remove"
										aria-label="Delete"
										onclick={(e) => {
											e.stopPropagation();
											void deleteTrailer(t);
										}}
									>
										<Trash2 size={13} />
									</button>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}

		{#if !loading && !loadError && offset < total}
			<div class="mt-4 text-center">
				<Button disabled={loadingMore} onclick={() => void loadLibrary(false)}>
					{loadingMore ? 'Loading…' : 'Load more'}
				</Button>
			</div>
		{/if}
	</div>

	{#if selectedId !== null}
		<DetailPanel
			label={detail?.title ?? 'Trailer'}
			ids={items.map((it) => it.id)}
			currentId={selectedId}
			loading={detailLoading}
			error={detailError}
			onclose={closeDetail}
			onstep={(id) => openDetail(id)}
		>
			{#if detail}
				{@const t = detail}
				<h2 class="text-xl leading-tight font-semibold">{t.title}</h2>
				<dl class="mt-4 space-y-2 text-sm">
					{#if t.year || t.month}
						<div class="flex justify-between gap-2">
							<dt class="text-muted">Year</dt>
							<dd>
								{#if t.year}
									<button
										type="button"
										class="hover:text-accent"
										onclick={() => filterYear(t.year!)}>{t.year}</button
									>
								{/if}{t.month ? ` · month ${t.month}` : ''}
							</dd>
						</div>
					{/if}
					<div class="flex items-center justify-between gap-2">
						<dt class="text-muted">Certification</dt>
						<dd>
							<Select
								value={t.content_rating ?? ''}
								class="!h-7 text-xs"
								onchange={(e) => updateRating(t.id, (e.currentTarget as HTMLSelectElement).value)}
							>
								{#each certOptions(t.content_rating) as o (o.value)}
									<option value={o.value}>{o.label}</option>
								{/each}
							</Select>
							{#if t.content_rating && !t.rating_ok}
								<span class="ml-1 text-warning" title="Rating not in configured set">
									<TriangleAlert size={12} class="inline" />
								</span>
							{/if}
						</dd>
					</div>
					{#if t.director}
						<div class="flex justify-between gap-2">
							<dt class="text-muted">Director</dt>
							<dd>
								<button
									type="button"
									class="hover:text-accent"
									onclick={() => filterDirector(t.director!)}>{t.director}</button
								>
							</dd>
						</div>
					{/if}
					{#if t.duration}
						<div class="flex justify-between gap-2">
							<dt class="text-muted">Duration</dt>
							<dd class="font-mono">{Math.round(t.duration)}s</dd>
						</div>
					{/if}
					{#if t.tmdbid}
						<div class="flex justify-between gap-2">
							<dt class="text-muted">TMDB id</dt>
							<dd class="font-mono">{t.tmdbid}</dd>
						</div>
					{/if}
					{#if (t.rating_lookups ?? {})[ratingsSystem]}
						<div class="flex justify-between gap-2">
							<dt class="text-muted">Rating lookup</dt>
							<dd class="min-w-0 truncate">{(t.rating_lookups ?? {})[ratingsSystem]}</dd>
						</div>
					{/if}
					<div class="flex justify-between gap-2">
						<dt class="text-muted">Linked movie</dt>
						<dd class="min-w-0 truncate">
							{#if t.associated_movie}
								{t.associated_movie.title} ({t.associated_movie.year ?? '-'})
							{:else}
								<span class="text-faint">not linked</span>
							{/if}
						</dd>
					</div>
					{#if t.genres?.length}
						<div>
							<dt class="mb-1 text-muted">Genres</dt>
							<dd class="flex flex-wrap gap-1">
								{#each t.genres as g (g)}
									<button
										type="button"
										class="rounded-sm bg-surface-3 px-1.5 py-0.5 text-xs text-muted hover:text-accent"
										title="Show {g} trailers"
										onclick={() => filterGenre(g)}>{g}</button
									>
								{/each}
							</dd>
						</div>
					{/if}
					<div>
						<dt class="mb-1 text-muted">Tags</dt>
						<dd class="flex flex-wrap items-center gap-1">
							{#each t.trailer_tags ?? [] as tg (tg.id)}
								<span
									class="inline-flex items-center gap-1 rounded-sm bg-surface-3 px-1.5 py-0.5 text-xs"
								>
									{tg.name}
									<button
										type="button"
										class="text-faint hover:text-danger"
										title="Remove tag"
										aria-label="Remove tag {tg.name}"
										onclick={() => detailRemoveTag(t, tg.id)}
									>
										<X size={10} />
									</button>
								</span>
							{/each}
							<input
								class="h-6 w-20 rounded-sm border border-border-strong bg-surface-2 px-1.5 text-xs
									placeholder:text-faint focus:border-accent-dim"
								placeholder="+ tag"
								list="dtTagOptions"
								bind:value={detailTagInput}
								onkeydown={(e) => {
									if (e.key === 'Enter') {
										e.preventDefault();
										void detailAddTag(t);
									}
								}}
							/>
							<datalist id="dtTagOptions">
								{#each knownTags.filter((kt) => !(t.trailer_tags ?? []).some((have) => have.id === kt.id)) as kt (kt.id)}
									<option value={kt.name}></option>
								{/each}
							</datalist>
						</dd>
					</div>
					<div class="flex justify-between gap-2">
						<dt class="text-muted">File</dt>
						<dd>
							{#if t.file_exists}
								<StatusLamp colour="green" quiet>On disk</StatusLamp>
							{:else}
								<StatusLamp colour="amber">Missing</StatusLamp>
							{/if}
						</dd>
					</div>
				</dl>
				<p class="mt-4 font-mono text-[10px] break-all text-faint" title={t.file_path ?? ''}>
					{t.file_path ?? '-'}
				</p>
			{/if}
			{#snippet actions()}
				{#if detail}
					{@const t = detail}
					<Button
						size="sm"
						variant="primary"
						disabled={!t.file_exists}
						onclick={() => playTrailer(t)}
					>
						<Play size={13} /> Play
					</Button>
					{#if t.tmdbid}
						<Button
							size="sm"
							disabled={jobActive}
							title="Pick a different video from TMDB and replace this file"
							onclick={() => openVideoPicker(t.tmdbid!, t.title, true)}
						>
							Replace video
						</Button>
					{/if}
					<Button size="sm" variant="danger" onclick={() => deleteTrailer(t, true)}>Delete</Button>
				{/if}
			{/snippet}
		</DetailPanel>
	{/if}
</div>

<Dialog
	bind:open={playOpen}
	title={playing ? `${playing.title}${playing.year ? ` (${playing.year})` : ''}` : 'Play'}
	class="max-w-3xl"
>
	{#if playing}
		<!-- svelte-ignore a11y_media_has_caption -->
		<video controls autoplay src={playing.stream_url} class="max-h-[70vh] w-full bg-black"></video>
	{/if}
</Dialog>

<Dialog bind:open={fetchOpen} title="Get trailers" size="2xl">
	<Tabs
		class="mb-3"
		tabs={FETCH_TABS}
		value={fetchTab}
		label="Ways to get trailers"
		onselect={(id) => {
			if (id === 'upload') resetUploadForm();
			fetchTab = id as typeof fetchTab;
		}}
	/>

	{#if keyMissing}
		<p
			class="mb-3 flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning"
		>
			<TriangleAlert size={14} class="mt-px shrink-0" />
			<span>
				No TMDB API key is set, so trailer downloads will fail.
				<a href="{base}/settings?tab=library" class="underline"
					>Add one in Settings → Library source</a
				>
				- a free key from themoviedb.org works.
			</span>
		</p>
	{/if}

	{#if fetchTab === 'search'}
		<p class="mb-3 text-sm text-muted">
			Search TMDB by title and download the trailer for one specific movie.
		</p>
		<label class="mb-1 block text-xs text-muted" for="fSearchTitle">Movie title</label>
		<Input
			id="fSearchTitle"
			bind:value={sQuery}
			oninput={onTitleSearchInput}
			placeholder="Search by title, e.g. Dune…"
		/>
		{#if sSearching}
			<div class="mt-3"><Spinner size="sm" label="Searching…" /></div>
		{:else if sNoKey && sQuery.trim().length >= 2}
			<p class="mt-3 text-sm text-muted">
				No TMDB API key configured -
				<a href="{base}/settings?tab=library" class="text-accent underline">add one in Settings</a> to
				search.
			</p>
		{:else if sResults !== null}
			{#if !sResults.length}
				<EmptyState
					icon={Search}
					title="No movies found"
					message="No TMDB results match that title. Check the spelling or try a shorter search."
					compact
				/>
			{:else}
				<div class="mt-3 max-h-72 overflow-y-auto rounded-md border border-border">
					<ul class="divide-y divide-border">
						{#each sResults as r (r.tmdbid)}
							<li class="flex items-center gap-3 px-3 py-2">
								{#if r.poster_url}
									<img
										src={r.poster_url}
										alt=""
										loading="lazy"
										class="h-12 w-8 shrink-0 rounded-xs object-cover"
									/>
								{:else}
									<span
										class="flex h-12 w-8 shrink-0 items-center justify-center rounded-xs bg-surface-3 text-faint"
									>
										<Film size={14} />
									</span>
								{/if}
								<span class="min-w-0 flex-1">
									<span class="block truncate text-sm">{r.title}</span>
									<span class="font-mono text-xs text-muted">{r.year ?? ''}</span>
								</span>
								{#if r.in_library}
									<Badge>In library</Badge>
								{/if}
								{#if r.has_trailer}
									<StatusLamp colour="green">Trailer downloaded</StatusLamp>
									<Button
										size="sm"
										disabled={jobActive}
										title="Pick a different video and replace the downloaded trailer"
										onclick={() => openVideoPicker(r.tmdbid, r.title, true)}
									>
										Replace…
									</Button>
								{:else}
									<Button
										size="sm"
										disabled={jobActive}
										title="Choose which of the movie's videos to download"
										onclick={() => openVideoPicker(r.tmdbid, r.title, false)}
									>
										Choose…
									</Button>
									<Button
										size="sm"
										variant="primary"
										disabled={jobActive}
										onclick={() => fetchSingle(r)}
									>
										<Download size={13} /> Download
									</Button>
								{/if}
							</li>
						{/each}
					</ul>
				</div>
			{/if}
		{/if}
	{:else if fetchTab === 'discover'}
		<p class="mb-3 text-sm text-muted">
			Search TMDB by date range, rating and certificate, and download the matching trailers.
		</p>
		<div class="grid grid-cols-2 gap-3 sm:grid-cols-3">
			<div>
				<label class="mb-1 block text-xs text-muted" for="fYearFrom">Year from</label>
				<Input id="fYearFrom" type="number" bind:value={fYearFrom} placeholder="e.g. 2024" />
			</div>
			<div>
				<label class="mb-1 block text-xs text-muted" for="fYearTo">Year to</label>
				<Input id="fYearTo" type="number" bind:value={fYearTo} placeholder="e.g. 2026" />
			</div>
			<div>
				<label class="mb-1 block text-xs text-muted" for="fLimit">Limit</label>
				<Input id="fLimit" type="number" bind:value={fLimit} />
			</div>
			<div>
				<label class="mb-1 block text-xs text-muted" for="fSort">Sort by</label>
				<Select id="fSort" bind:value={fSort} class="w-full">
					<option value="popularity.desc">Popularity (high - low)</option>
					<option value="popularity.asc">Popularity (low - high)</option>
					<option value="release_date.desc">Release date (newest)</option>
					<option value="release_date.asc">Release date (oldest)</option>
					<option value="vote_average.desc">Rating (high - low)</option>
				</Select>
			</div>
			<div>
				<label class="mb-1 block text-xs text-muted" for="fMinRating">Min TMDB rating</label>
				<Input id="fMinRating" type="number" bind:value={fMinRating} placeholder="e.g. 6.0" />
			</div>
			<div>
				<label class="mb-1 block text-xs text-muted" for="fCert">Certification (GB)</label>
				<Select id="fCert" bind:value={fCert} class="w-full">
					<option value="">Any</option>
					<option value="U">U</option>
					<option value="PG">PG</option>
					<option value="12A">12A</option>
					<option value="15">15</option>
					<option value="18">18</option>
				</Select>
			</div>
		</div>
		<div class="mt-3 flex gap-2">
			<Button size="sm" onclick={runPreview}>Preview (dry run)</Button>
			<Button size="sm" variant="primary" onclick={() => runFetch('discover')}>Fetch</Button>
		</div>

		{#if previewMsg}
			<p class="mt-3 text-sm text-muted">{previewMsg}</p>
		{:else if preview}
			{#if !preview.trailers.length}
				<EmptyState
					icon={Search}
					title="No trailers found"
					message="No TMDB results match these criteria. Widen the year range, lower the minimum rating, or change the certification, then preview again."
					compact
				/>
			{:else}
				<p class="mt-3 text-sm">
					Found <strong>{preview.total_found}</strong> · Will fetch
					<strong>{preview.will_fetch}</strong>
					· Already have <strong>{preview.already_have}</strong>
				</p>
				<div class="mt-2 max-h-56 overflow-y-auto border border-border">
					<table class="w-full text-xs">
						<thead>
							<tr class="border-b border-border bg-surface-2 text-left font-medium text-muted">
								<th class="px-2 py-1.5">Title</th>
								<th class="px-2 py-1.5">Year</th>
								<th class="px-2 py-1.5">Genres</th>
								<th class="px-2 py-1.5">Rating</th>
								<th class="px-2 py-1.5">Status</th>
							</tr>
						</thead>
						<tbody class="divide-y divide-border">
							{#each preview.trailers as pt, i (i)}
								<tr>
									<td class="max-w-52 truncate px-2 py-1">{pt.title}</td>
									<td class="px-2 py-1 font-mono">{pt.year ?? ''}</td>
									<td class="max-w-36 truncate px-2 py-1 text-muted">
										{(pt.genres ?? []).slice(0, 2).join(', ')}
									</td>
									<td class="px-2 py-1 font-mono">
										{pt.rating ? Number(pt.rating).toFixed(1) : '-'}
									</td>
									<td class="px-2 py-1">
										{#if pt.already_downloaded}
											<StatusLamp colour="green" quiet>Already have</StatusLamp>
										{:else}
											<Badge>new</Badge>
										{/if}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		{/if}
	{:else if fetchTab === 'upload'}
		<p class="mb-3 text-sm text-muted">
			Add a trailer you already have as a file. Link it to a movie so the trailer rules can match
			it, or leave it unlinked for an ident or a custom clip.
		</p>
		<div class="space-y-3">
			<button
				type="button"
				class="flex w-full flex-col items-center gap-1 rounded-md border-2 border-dashed px-4 py-6
				text-center transition-colors
				{upDragOver ? 'border-accent bg-accent/5' : 'border-border-strong hover:border-accent-dim'}"
				onclick={() => upFileInput?.click()}
				ondragover={(e) => {
					e.preventDefault();
					upDragOver = true;
				}}
				ondragenter={(e) => {
					e.preventDefault();
					upDragOver = true;
				}}
				ondragleave={(e) => {
					e.preventDefault();
					upDragOver = false;
				}}
				ondrop={onUploadDrop}
			>
				<CloudUpload size={22} class="text-faint" />
				<span class="text-sm"><strong>Drag a trailer file here</strong> or click to browse</span>
				<span class="text-xs text-faint">MP4, MKV or MOV - stored in your trailer directory</span>
			</button>
			<input
				bind:this={upFileInput}
				type="file"
				accept=".mp4,.mkv,.mov,video/*"
				hidden
				onchange={(e) => {
					const input = e.currentTarget as HTMLInputElement;
					if (input.files?.[0]) setUploadFile(input.files[0]);
					input.value = '';
				}}
			/>

			{#if upFile}
				<p class="flex items-center gap-2 text-xs text-muted">
					<Film size={13} />
					<span class="min-w-0 truncate" title={upFile.name}>{upFile.name}</span>
					<span class="shrink-0 font-mono">{(upFile.size / (1024 * 1024)).toFixed(1)} MB</span>
				</p>
			{/if}

			<div>
				<label class="mb-1 block text-xs text-muted" for="upTmdbSearch">
					Link to TMDB <span class="text-faint">(optional)</span>
				</label>
				<Input
					id="upTmdbSearch"
					bind:value={upTmdbSearch}
					oninput={onTmdbSearchInput}
					placeholder="Search TMDB by title…"
				/>
				{#if upTmdbResults !== null}
					<div class="mt-1 max-h-44 overflow-y-auto rounded-md border border-border bg-surface-2">
						{#if upTmdbNoKey}
							<p class="px-3 py-2 text-xs text-muted">
								No TMDB API key configured -
								<a href="{base}/settings?tab=library" class="text-accent underline"
									>add one in Settings</a
								>
								to link uploads. Unlinked uploads work fine.
							</p>
						{:else if !upTmdbResults.length}
							<p class="px-3 py-2 text-xs text-muted">No TMDB matches for "{upTmdbSearch}"</p>
						{:else}
							{#each upTmdbResults as r (r.tmdbid)}
								<button
									type="button"
									class="flex w-full items-center gap-2 px-2 py-1.5 text-left hover:bg-surface-3"
									onclick={() => selectTmdb(r)}
								>
									{#if r.poster_url}
										<img
											src={r.poster_url}
											alt=""
											loading="lazy"
											class="h-10 w-7 shrink-0 rounded-xs object-cover"
										/>
									{:else}
										<span
											class="flex h-10 w-7 shrink-0 items-center justify-center rounded-xs bg-surface-3 text-faint"
										>
											<Film size={12} />
										</span>
									{/if}
									<span class="min-w-0 flex-1 truncate text-sm">{r.title}</span>
									<span class="shrink-0 font-mono text-xs text-muted">{r.year ?? ''}</span>
								</button>
							{/each}
						{/if}
					</div>
				{/if}
				{#if upTmdb}
					<p class="mt-1.5 flex items-center gap-2 text-xs">
						<span class="min-w-0 truncate"
							>{upTmdb.title}{upTmdb.year ? ` (${upTmdb.year})` : ''}</span
						>
						<Badge variant="accent"><LinkIcon size={9} /> TMDB {upTmdb.tmdbid}</Badge>
						<button
							type="button"
							class="text-faint hover:text-danger"
							title="Clear TMDB link"
							aria-label="Clear TMDB link"
							onclick={() => (upTmdb = null)}
						>
							<X size={12} />
						</button>
					</p>
				{/if}
				<p class="mt-1 text-xs text-faint">
					Linking fills the title, year, genres and certificates automatically - and connects the
					trailer to that movie in your library. Leave unlinked for idents and custom clips.
				</p>
			</div>

			<div>
				<label class="mb-1 block text-xs text-muted" for="upTitle">Title</label>
				<Input id="upTitle" bind:value={upTitle} placeholder="Trailer title" />
			</div>

			<div>
				<span class="mb-1 block text-xs text-muted">Trailer tags</span>
				{#if uploadTagChoices.length}
					<div class="mb-1.5 flex flex-wrap gap-1">
						{#each uploadTagChoices as name (name)}
							{@const on = upTagNames.includes(name)}
							<button
								type="button"
								class="inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-xs
								{on ? 'bg-accent/15 text-accent' : 'bg-surface-3 text-muted hover:text-text'}"
								onclick={() => toggleUploadTag(name)}
							>
								<Tag size={9} />{name}
							</button>
						{/each}
					</div>
				{:else}
					<p class="mb-1.5 text-xs text-faint">No trailer tags yet - type one below.</p>
				{/if}
				<input
					class="h-9 w-full rounded-md border border-border-strong bg-surface-2 px-3 text-sm
					placeholder:text-faint focus:border-accent-dim"
					placeholder="New tag - press Enter to add…"
					bind:value={upTagInput}
					onkeydown={(e) => {
						if (e.key === 'Enter') {
							e.preventDefault();
							addUploadTag();
						}
					}}
				/>
			</div>

			{#if upBusy}
				<div>
					<div class="h-1.5 overflow-hidden rounded-xs bg-surface-3">
						<div
							class="h-full bg-accent transition-[width]"
							style="width: {Math.round(upPct)}%"
						></div>
					</div>
					<p class="mt-1 text-xs text-muted">
						{upPct >= 100 ? 'Processing…' : `${Math.round(upPct)}%`}
					</p>
				</div>
			{/if}
		</div>
		<div class="mt-3">
			<Button size="sm" variant="primary" disabled={upBusy} onclick={submitUpload}>
				<Upload size={13} /> Upload
			</Button>
		</div>
	{:else if fetchTab === 'library'}
		<p class="mb-3 text-sm text-muted">
			Download trailers for movies already in your library that don't have one yet.
		</p>
		<Button size="sm" variant="primary" onclick={() => runFetch('library')}>
			Fetch library trailers
		</Button>
	{:else if fetchTab === 'verify'}
		<p class="mb-3 text-sm text-muted">
			Reconcile the trailer directory against the database. Finds missing files, re-links moved
			trailers, and imports orphaned files that contain a recognisable TMDB ID.
		</p>
		<Button size="sm" variant="primary" onclick={runVerify}>Run verify</Button>
	{:else}
		<p class="mb-3 text-sm text-muted">
			Looks up certificates for <strong class="text-text">trailers</strong> that have none yet - or one
			from a different scheme (e.g. an MPAA rating on a BBFC install) - directly from the classification
			body (bbfc.co.uk / filmratings.com). Movies are rated separately, from the library's sync panel.
		</p>
		<Button size="sm" variant="primary" onclick={runRatings}>Update certificate ratings</Button>
	{/if}

	{#if trailerJob}
		<div class="mt-4">
			<JobProgress kind="trailer" job={trailerJob} opLabels={OP_LABEL} />
		</div>
	{/if}
</Dialog>

<Dialog
	bind:open={vpOpen}
	title={vpReplace ? `Replace trailer - ${vpTitle}` : `Choose video - ${vpTitle}`}
	class="max-w-lg"
>
	{#if vpError}
		<p class="text-sm text-danger">{vpError}</p>
	{:else if vpVideos === null}
		<Spinner size="sm" label="Loading videos…" />
	{:else if !vpVideos.length}
		<EmptyState
			icon={Clapperboard}
			title="No videos listed"
			message="TMDB lists no YouTube videos for this movie. Upload a file instead, or try again later."
			compact
		/>
	{:else}
		{#if vpReplace}
			<p class="mb-2 text-xs text-muted">
				The downloaded file is replaced; the trailer's tags, certificate and movie link stay.
			</p>
		{/if}
		<ul class="max-h-80 divide-y divide-border overflow-y-auto rounded-md border border-border">
			{#each vpVideos as v (v.key)}
				<li class="flex items-center gap-3 px-3 py-2">
					<span class="min-w-0 flex-1">
						<span class="block truncate text-sm" title={v.name}>{v.name}</span>
						<span class="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-muted">
							<Badge>{v.type || 'Video'}</Badge>
							{#if v.official}
								<Badge variant="accent">Official</Badge>
							{/if}
							{#if v.size}
								<span class="font-mono">{v.size}p</span>
							{/if}
							{#if v.published_at}
								<span class="font-mono">{v.published_at.slice(0, 10)}</span>
							{/if}
						</span>
					</span>
					<a
						class="shrink-0 text-xs text-muted underline hover:text-text"
						href="https://www.youtube.com/watch?v={v.key}"
						target="_blank"
						rel="noreferrer"
						title="Watch on YouTube before downloading"
					>
						Preview
					</a>
					<Button size="sm" variant="primary" disabled={jobActive} onclick={() => fetchVideo(v)}>
						<Download size={13} />
						{vpReplace ? 'Replace' : 'Download'}
					</Button>
				</li>
			{/each}
		</ul>
	{/if}
</Dialog>

<Dialog bind:open={bulkTagOpen} title="Tag selected trailers">
	<p class="mb-3 text-sm text-muted">
		Apply one tag to {selected.size} selected trailer{selected.size === 1 ? '' : 's'}.
	</p>
	<label class="mb-1 block text-xs text-muted" for="bulkTagInput">Tag</label>
	<input
		id="bulkTagInput"
		class="h-9 w-full rounded-md border border-border-strong bg-surface-2 px-3 text-sm
			placeholder:text-faint focus:border-accent-dim"
		bind:value={bulkTagName}
		placeholder="Tag name (created if new)"
		list="bulkTagOptions"
	/>
	<datalist id="bulkTagOptions">
		{#each knownTags as t (t.id)}
			<option value={t.name}></option>
		{/each}
	</datalist>
	{#snippet footer()}
		<Button onclick={() => (bulkTagOpen = false)}>Cancel</Button>
		<Button variant="primary" disabled={bulkTagBusy} onclick={applyBulkTag}>
			<Tags size={13} /> Apply tag
		</Button>
	{/snippet}
</Dialog>

<Dialog bind:open={renameOpen} title="Rename to naming scheme" size="2xl">
	{#if renameMsg}
		<p class="text-sm text-muted">{renameMsg}</p>
	{:else if renamePlan}
		{#if !renameChanges.length}
			<p class="text-sm text-muted">
				Nothing to rename - all {renamePlan.total} files already match the scheme.
			</p>
		{:else}
			<p class="mb-2 text-sm">
				<strong>{renameChanges.length}</strong> file(s) will be renamed
				{#if renameConflicts.length}
					· <span class="text-warning">{renameConflicts.length} conflict(s) skipped</span>
				{/if}
			</p>
			<div class="max-h-64 overflow-y-auto border border-border">
				<table class="w-full text-xs">
					<thead>
						<tr class="border-b border-border bg-surface-2 text-left font-medium text-muted">
							<th class="px-2 py-1.5">Title</th>
							<th class="px-2 py-1.5">Change</th>
						</tr>
					</thead>
					<tbody class="divide-y divide-border">
						{#each renameChanges.slice(0, 2000) as c, i (i)}
							<tr>
								<td class="max-w-44 truncate px-2 py-1">{c.label}</td>
								<td class="px-2 py-1 font-mono break-all text-muted">{c.detail}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	{/if}
	{#snippet footer()}
		<Button onclick={() => (renameOpen = false)}>Close</Button>
		{#if renameChanges.length}
			<Button variant="primary" disabled={renameBusy} onclick={applyRename}>
				{renameBusy ? 'Renaming…' : 'Apply rename'}
			</Button>
		{/if}
	{/snippet}
</Dialog>

<Dialog bind:open={matchOpen} title="Test trailer matching" size="2xl">
	<div class="space-y-3">
		<div>
			<label class="mb-1 block text-xs text-muted" for="matchSearch">Choose a movie</label>
			<Input
				id="matchSearch"
				type="search"
				bind:value={matchSearch}
				oninput={onMatchSearchInput}
				placeholder="Search your library…"
			/>
			{#if matchResults.length}
				<div class="mt-1 max-h-44 overflow-y-auto rounded-md border border-border bg-surface-2">
					{#each matchResults as m (m.id)}
						<button
							type="button"
							class="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-surface-3"
							onclick={() => runMatchTest(m.id)}
						>
							<span class="min-w-0 flex-1 truncate">{m.title}</span>
							<span class="shrink-0 font-mono text-xs text-muted">{m.year ?? ''}</span>
						</button>
					{/each}
				</div>
			{/if}
		</div>

		{#if matchMsg}
			<p class="text-sm text-muted">{matchMsg}</p>
		{:else if matchData}
			<p class="text-sm">
				<strong>{matchData.movie_title}</strong>
				<span class="text-muted">
					- {matchData.matched} candidate {matchData.matched === 1 ? 'trailer' : 'trailers'},
					ranked; the top {Math.min(matchData.requested, matchData.matched)} would play
				</span>
			</p>
			{#if !matchData.trailers.length}
				<p class="text-sm text-muted">No trailers match - fetch some, or loosen the rule.</p>
			{:else}
				<div
					class="max-h-64 divide-y divide-border overflow-y-auto rounded-md border border-border"
				>
					{#each matchData.trailers as mt (mt.id)}
						<div
							class="flex items-center gap-2 px-2.5 py-1.5 text-xs {mt.will_play
								? ''
								: 'opacity-55'}"
						>
							{#if mt.will_play}
								<StatusLamp colour="green">Would play</StatusLamp>
							{/if}
							<span class="min-w-0 flex-1 truncate">{mt.title}</span>
							<span class="shrink-0 font-mono text-muted">
								{mt.year ?? ''}{mt.content_rating ? ` · ${mt.content_rating}` : ''}
							</span>
						</div>
					{/each}
				</div>
			{/if}
		{:else}
			<p class="text-sm text-muted">
				Pick a movie to see which trailers a rule would select for it, in ranked order.
			</p>
		{/if}
	</div>
</Dialog>
