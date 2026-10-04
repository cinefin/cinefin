<script lang="ts">
	import PageHeader from '$lib/components/shell/PageHeader.svelte';
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
	import { ApiError, api, unwrap } from '$lib/api/client';
	import { uploadWithProgress } from '$lib/upload';
	import { query } from '$lib/api/query.svelte';
	import { liveRefresh } from '$lib/live.svelte';
	import { sortIndicator, toggleSort, type FilterControl, type SortSpec } from '$lib/filters';
	import { formatSize, formatTime } from '$lib/format';
	import type { components } from '$lib/api/types.gen';
	import { replaceState } from '$app/navigation';
	import { unwrapLoose, type JobEvent } from '$lib/jobs';
	import { TrailerJob } from '$lib/trailers/job.svelte';
	import { showToast, toastFailure } from '$lib/toast.svelte';
	import { act } from '$lib/media/actions';
	import { Selection } from '$lib/selection.svelte';
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
		file_size: number | null;
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

	interface LibraryData {
		trailers: Trailer[];
		total: number;
		stats: { total: number; with_file: number; missing: number; rating_issues: number };
		facets: {
			ratings: string[];
			genres: string[];
			valid_ratings: string[];
			trailer_tags: TrailerTag[];
		};
	}

	interface TmdbResult {
		tmdbid: number;
		title: string;
		year: number | null;
		poster_url: string | null;
		has_trailer: boolean;
		in_library: boolean;
	}

	/** A request as openapi-fetch hands it back. */
	type Pending = PromiseLike<{ data?: unknown; error?: unknown; response: Response }>;

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
	let stats = $state<LibraryData['stats'] | null>(null);
	let facets = $state<LibraryData['facets'] | null>(null);
	let loading = $state(true);
	let loadError = $state<ApiError | null>(null);
	let loadingMore = $state(false);
	// Declared before the init reload(), which clears it.
	const selected = new Selection(() => items);

	let view = $state<'grid' | 'list'>(localStorage.getItem('tl_view') === 'list' ? 'list' : 'grid');

	const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`;

	const ratingIssue = $derived(rating === ISSUES);
	const filtersActive = $derived(Boolean(q || genre || rating || missing || year || tag));

	function buildParams() {
		const params: Record<string, string | number | boolean> = { limit: LIMIT, offset, sort };
		if (q) params.q = q;
		if (genre) params.genre = genre;
		if (rating && !ratingIssue) params.rating = rating;
		if (ratingIssue) params.rating_issue = true;
		if (year) params.year = year;
		if (tag) params.tag = Number(tag);
		if (missing) params.missing = true;
		return params;
	}

	/**
	 * reset: the first page, visibly; more: the next page; refresh: everything shown, silently
	 * (a background refresh keeps what's on screen when it fails).
	 */
	let loadSeq = 0;
	async function loadLibrary(mode: 'reset' | 'more' | 'refresh') {
		if (mode === 'refresh' && (loading || loadingMore)) return;
		const seq = ++loadSeq;
		if (mode === 'reset') {
			offset = 0;
			loading = true;
			loadError = null;
		} else if (mode === 'more') loadingMore = true;
		const params = buildParams();
		if (mode === 'refresh')
			Object.assign(params, { offset: 0, limit: Math.max(LIMIT, items.length) });
		try {
			const data = await unwrapLoose<LibraryData>(
				api.GET('/api/v2/trailers/library', { params: { query: params } })
			);
			if (seq !== loadSeq) return;
			items = mode === 'more' ? [...items, ...data.trailers] : data.trailers;
			total = data.total;
			stats = data.stats;
			offset = items.length;
			loadError = null;
			// Genre/rating facets load once; tags and valid ratings follow every fetch.
			if (!facets) facets = data.facets;
			else {
				facets.trailer_tags = data.facets.trailer_tags;
				facets.valid_ratings = data.facets.valid_ratings;
			}
		} catch (e) {
			if (seq !== loadSeq) return;
			if (mode === 'reset') loadError = e instanceof ApiError ? e : new ApiError(String(e), 0);
			else if (mode === 'more') toastFailure('Failed to load more', e);
		} finally {
			if (seq === loadSeq) {
				loading = false;
				loadingMore = false;
			}
		}
	}

	const refreshLibrary = () => loadLibrary('refresh');

	function reload() {
		selected.clear();
		void loadLibrary('reset');
	}

	$effect(() => liveRefresh(() => void refreshLibrary()));

	function clearFilters() {
		q = genre = rating = tag = '';
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
		offset < total ? `Showing ${offset} of ${total} trailers` : plural(total, 'trailer')
	);

	/** An onchange that sets one filter and reloads. */
	function on<T>(set: (v: T) => void) {
		return (v: T) => {
			set(v);
			reload();
		};
	}

	const options = (values: string[] | undefined) =>
		(values ?? []).map((v) => ({ value: v, label: v }));

	const filterControls = $derived<FilterControl[]>([
		{
			id: 'genre',
			label: 'Genre',
			allLabel: 'All genres',
			value: genre,
			options: options(facets?.genres),
			onchange: on((v: string) => (genre = v))
		},
		{
			id: 'rating',
			label: 'Rating',
			allLabel: 'All ratings',
			value: rating,
			options: [
				...options(facets?.ratings),
				{ value: ISSUES, label: 'Rating problems', count: stats?.rating_issues || undefined }
			],
			onchange: on((v: string) => (rating = v))
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
						onchange: on((v: string) => (tag = v))
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
			onchange: on((v: string) => (year = v ? Number(v) : null))
		},
		{
			kind: 'toggle',
			id: 'missing',
			label: 'Missing file',
			value: missing,
			onchange: on((v: boolean) => (missing = v))
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
		onchange: on((v: string) => (sort = v))
	});

	const ratingsOptions = query(() => unwrap(api.GET('/api/v2/movies/ratings-options')));
	const ratingsSystem = $derived(ratingsOptions.data?.system ?? 'BBFC');

	function certOptions(current: string | null): { value: string; label: string }[] {
		const ordered = ratingsOptions.data?.ratings?.length
			? ratingsOptions.data.ratings
			: (facets?.valid_ratings ?? []);
		const opts = [{ value: '', label: '- none -' }];
		if (current && !ordered.includes(current)) {
			opts.push({ value: current, label: `${current} (not ${ratingsSystem})` });
		}
		return [...opts, ...options(ordered)];
	}

	/** Narrow the list from a clicked fact (year, genre, director…) and close the drawer. */
	function filterBy(set: () => void) {
		set();
		closeDetail();
		reload();
	}
	const filterYear = (y: number) => filterBy(() => (year = y));
	const filterGenre = (g: string) => filterBy(() => (genre = g));
	const filterDirector = (d: string) => filterBy(() => (q = d));

	/** A click handler that doesn't also open the card it sits on. */
	const stop = (fn: () => void) => (e: Event) => {
		e.stopPropagation();
		fn();
	};

	let confirmDialog: ConfirmDialog;

	/** After a change: refetch what's shown, and tell other pages the trailers changed. */
	function changed() {
		void refreshLibrary();
		invalidate('trailers');
	}

	async function bulkDeleteSelected() {
		const ids = [...selected];
		if (!ids.length) return;
		const ok = await confirmDialog.confirm(
			`Remove ${plural(ids.length, 'trailer')} from the library? This deletes the records AND the files on disk.`
		);
		if (!ok) return;
		await act('Bulk delete failed', async () => {
			const res = await unwrapLoose<{ deleted: number; file_errors?: string[] }>(
				api.POST('/api/v2/trailers/library/bulk-delete', { body: { ids, delete_files: true } })
			);
			selected.clear();
			items = items.filter((x) => !ids.includes(x.id));
			total -= res.deleted;
			const errs = res.file_errors?.length
				? ` (${plural(res.file_errors.length, 'file')} could not be removed)`
				: '';
			showToast(`Removed ${plural(res.deleted, 'trailer')}${errs}`, errs ? 'warning' : 'success');
			changed();
		});
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
		if (!name) return showToast('Enter a tag name', 'error');
		bulkTagBusy = true;
		await act('Tagging failed', async () => {
			const res = await unwrapLoose<{ tagged: number; tag: TrailerTag }>(
				api.POST('/api/v2/trailers/library/bulk-tag', { body: { ids: [...selected], name } })
			);
			bulkTagOpen = false;
			showToast(`Tagged ${plural(res.tagged, 'trailer')} with "${res.tag.name}"`, 'success');
			selected.clear();
			void refreshLibrary();
		});
		bulkTagBusy = false;
	}

	const sortCols: { key: string; label: string; defaultDesc?: boolean }[] = [
		{ key: 'title', label: 'Title' },
		{ key: 'year', label: 'Year', defaultDesc: true },
		{ key: 'content_rating', label: 'Cert' },
		{ key: 'duration', label: 'Duration', defaultDesc: true },
		{ key: 'file_size', label: 'Size', defaultDesc: true }
	];

	function headerSort(key: string, defaultDesc?: boolean) {
		sort = toggleSort(sort, key, defaultDesc);
		reload();
	}

	let selectedId = $state<number | null>(null);
	let detail = $state<Trailer | null>(null);
	let detailLoading = $state(false);
	let detailError = $state<string | null>(null);
	let autoplay = $state(false);

	async function openDetail(id: number, play = false) {
		autoplay = play;
		selectedId = id;
		detail = null;
		detailError = null;
		detailLoading = true;
		try {
			const data = await unwrapLoose<{ trailer: Trailer }>(
				api.GET('/api/v2/trailers/library/{trailer_id}', { params: { path: { trailer_id: id } } })
			);
			if (selectedId === id) detail = data.trailer;
		} catch (e) {
			if (selectedId === id)
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

	function refreshTagFacet() {
		unwrapLoose<{ tags: TrailerTag[] }>(api.GET('/api/v2/trailers/tags'))
			.then((res) => {
				if (facets) facets.trailer_tags = res.tags ?? [];
			})
			.catch(() => {}); // facet refresh is cosmetic
	}

	let detailTagInput = $state('');

	function editTags(t: Trailer, verb: 'add' | 'remove', req: Pending) {
		void act(`Could not ${verb} tag`, async () => {
			const res = await unwrapLoose<{ trailer_tags: TrailerTag[] }>(req);
			t.trailer_tags = res.trailer_tags;
			const item = items.find((x) => x.id === t.id);
			if (item) item.trailer_tags = res.trailer_tags;
			if (verb === 'add') detailTagInput = '';
			void refreshLibrary();
		});
	}

	function detailAddTag(t: Trailer) {
		const name = detailTagInput.trim();
		if (!name) return;
		const path = { trailer_id: t.id };
		editTags(
			t,
			'add',
			api.POST('/api/v2/trailers/library/{trailer_id}/tags', { params: { path }, body: { name } })
		);
	}

	function detailRemoveTag(t: Trailer, tagId: number) {
		const path = { trailer_id: t.id, tag_id: tagId };
		editTags(
			t,
			'remove',
			api.DELETE('/api/v2/trailers/library/{trailer_id}/tags/{tag_id}', { params: { path } })
		);
	}

	function updateRating(id: number, value: string) {
		void act('Update failed', async () => {
			const { trailer: updated } = await unwrapLoose<{ trailer: Trailer }>(
				api.PATCH('/api/v2/trailers/library/{trailer_id}', {
					params: { path: { trailer_id: id } },
					body: { content_rating: value }
				})
			);
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
		});
	}

	async function deleteTrailer(t: Trailer, fromDetail = false) {
		const ok = await confirmDialog.confirm(
			`Remove "${t.title}" from the library? This deletes the record AND the file on disk.`
		);
		if (!ok) return;
		await act('Delete failed', async () => {
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
			changed();
		});
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

	const job = new TrailerJob(onJobComplete);
	$effect(() => job.follow());

	function onJobComplete(p: JobEvent) {
		const parts = Object.entries(p.counts ?? {})
			.filter(([, v]) => typeof v === 'number' && v)
			.map(([k, v]) => `${k}: ${v}`);
		const summary = p.error
			? `${OP_LABEL[p.operation] || 'Job'} ${p.state}: ${String(p.error).split('\n')[0]}`
			: `${OP_LABEL[p.operation] || 'Job'} ${p.state}${parts.length ? ' - ' + parts.join(', ') : ''}`;
		showToast(summary, p.state === 'success' ? 'success' : p.state === 'failed' ? 'error' : 'info');
		changed();
		if (sResults?.length) void runTitleSearch();
		if (selectedId !== null) void openDetail(selectedId);
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
	let fetchTab = $state('search');
	let keyMissing = $state(false);

	// Discover's criteria; the keys name their inputs' ids (`f<Key>`).
	const disc = $state({
		YearFrom: '',
		YearTo: '',
		Limit: '50',
		Sort: 'popularity.desc',
		MinRating: '',
		Cert: ''
	});
	const DISC_HINTS: Record<string, string> = {
		YearFrom: 'e.g. 2024',
		YearTo: 'e.g. 2026',
		MinRating: 'e.g. 6.0'
	};

	function openFetchDialog() {
		fetchOpen = true;
		void job.reattach();
		unwrapLoose<{ settings: { tmdb_api_key?: string } }>(api.GET('/api/v2/trailers/settings'))
			.then((data) => {
				keyMissing = !(data.settings?.tmdb_api_key || '').trim();
			})
			.catch(() => {}); // leave the notice hidden
	}

	function debounced(ms: number, fn: () => void) {
		let timer: ReturnType<typeof setTimeout> | undefined;
		return () => {
			clearTimeout(timer);
			timer = setTimeout(fn, ms);
		};
	}

	const tmdbSearch = (q: string, limit?: number) =>
		unwrapLoose<{ results: TmdbResult[]; api_key_configured: boolean }>(
			api.GET('/api/v2/trailers/tmdb-search', { params: { query: limit ? { q, limit } : { q } } })
		);

	let sQuery = $state('');
	let sResults = $state<TmdbResult[] | null>(null);
	let sSearching = $state(false);
	let sNoKey = $state(false);

	async function runTitleSearch() {
		const term = sQuery.trim();
		if (term.length < 2) {
			sResults = null;
			return;
		}
		sSearching = true;
		try {
			const res = await tmdbSearch(term, 10);
			sNoKey = !res.api_key_configured;
			sResults = res.results;
		} catch (e) {
			sResults = null;
			toastFailure('Search failed', e);
		} finally {
			sSearching = false;
		}
	}

	const onTitleSearchInput = debounced(300, () => void runTitleSearch());

	// months_ahead/limit/sort_by carry schema defaults the backend ignores outside discover.
	const FETCH_DEFAULTS = { months_ahead: 6, limit: 50, sort_by: 'popularity.desc', replace: false };

	function fetchSingle(tmdbid: number, extra: { video_key?: string; replace?: boolean } = {}) {
		const body = { ...FETCH_DEFAULTS, type: 'single' as const, tmdbid, ...extra };
		void job.start(() => api.POST('/api/v2/trailers/fetch', { body }));
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
	let vp = $state({ title: '', tmdbid: 0, replace: false });
	let vpVideos = $state<TmdbVideo[] | null>(null);
	let vpError = $state<string | null>(null);

	async function openVideoPicker(tmdbid: number, title: string, replace: boolean) {
		vp = { title, tmdbid, replace };
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
		fetchSingle(vp.tmdbid, { video_key: v.key, replace: vp.replace });
	}

	// Unset fields stay undefined, so JSON drops them.
	function buildFetchParams() {
		const int = (v: string) => (v ? parseInt(v, 10) : undefined);
		return {
			sort_by: disc.Sort,
			limit: int(disc.Limit) || 50,
			year_from: int(disc.YearFrom),
			year_to: int(disc.YearTo),
			min_rating: disc.MinRating ? parseFloat(disc.MinRating) : undefined,
			certification: disc.Cert || undefined
		};
	}

	let preview = $state<components['schemas']['PreviewTrailersDataSchema'] | null>(null);
	let previewMsg = $state<string | null>(null);

	async function runPreview() {
		preview = null;
		previewMsg = 'Querying TMDB…';
		try {
			preview = await unwrap(api.POST('/api/v2/trailers/preview', { body: buildFetchParams() }));
			previewMsg = null;
		} catch (e) {
			previewMsg = `Preview failed: ${e instanceof Error ? e.message : e}`;
		}
	}

	function runFetch(type: 'discover' | 'library') {
		const body = { ...FETCH_DEFAULTS, type, ...(type === 'discover' ? buildFetchParams() : {}) };
		void job.start(() => api.POST('/api/v2/trailers/fetch', { body }));
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

	const renameRun = <T,>(dry_run: boolean) =>
		unwrapLoose<T>(api.POST('/api/v2/trailers/library/rename', { params: { query: { dry_run } } }));

	async function openRename() {
		renamePlan = null;
		renameMsg = 'Computing preview…';
		renameOpen = true;
		try {
			renamePlan = (await renameRun<{ plan: NonNullable<typeof renamePlan> }>(true)).plan;
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
		await act('Rename failed', async () => {
			const res = await renameRun<{ counts: Record<string, number> }>(false);
			showToast(`Renamed ${res.counts?.renamed || 0} file(s)`, 'success');
			renameOpen = false;
			void refreshLibrary();
		});
		renameBusy = false;
	}

	let matchOpen = $state(false);
	let matchSearch = $state('');
	let matchResults = $state<{ id: number; title: string; year: number | null }[]>([]);
	let matchData = $state<components['schemas']['MatchTestDataSchema'] | null>(null);
	let matchMsg = $state<string | null>(null);

	const onMatchSearchInput = debounced(250, async () => {
		const term = matchSearch.trim();
		if (term.length < 2) {
			matchResults = [];
			return;
		}
		try {
			const data = await unwrap(
				api.GET('/api/v2/movies/list', { params: { query: { search: term, per_page: 8 } } })
			);
			matchResults = data.items.map((m) => ({ id: m.id, title: m.title, year: m.year ?? null }));
		} catch {
			matchResults = [];
		}
	});

	async function runMatchTest(movieId: number) {
		matchResults = [];
		matchSearch = '';
		matchData = null;
		matchMsg = 'Matching…';
		try {
			matchData = await unwrap(
				api.GET('/api/v2/trailers/match-test', { params: { query: { movie_id: movieId } } })
			);
			matchMsg = null;
		} catch {
			matchMsg = 'Could not run the match test.';
		}
	}

	const blankUpload = () => ({
		file: null as File | null,
		title: '',
		tmdb: null as TmdbResult | null,
		tmdbSearch: '',
		tmdbResults: null as TmdbResult[] | null,
		tmdbNoKey: false,
		tags: [] as string[],
		tagInput: '',
		busy: false,
		pct: 0
	});
	let up = $state(blankUpload());
	let upDragOver = $state(false);
	let upFileInput = $state<HTMLInputElement | undefined>();

	function resetUploadForm() {
		up = blankUpload();
		refreshTagFacet();
	}

	function setUploadFile(f: File) {
		up.file = f;
		if (!up.title.trim() && !up.tmdb) up.title = f.name.replace(/\.[^.]+$/, '');
	}

	function onUploadDrag(e: DragEvent) {
		e.preventDefault();
		upDragOver = e.type !== 'dragleave' && e.type !== 'drop';
		const f = e.type === 'drop' ? e.dataTransfer?.files?.[0] : undefined;
		if (f) setUploadFile(f);
	}

	const onTmdbSearchInput = debounced(300, async () => {
		const term = up.tmdbSearch.trim();
		if (term.length < 2) {
			up.tmdbResults = null;
			return;
		}
		try {
			const res = await tmdbSearch(term);
			up.tmdbNoKey = !res.api_key_configured;
			up.tmdbResults = res.results;
		} catch {
			up.tmdbResults = null;
		}
	});

	function selectTmdb(r: TmdbResult) {
		up.tmdb = r;
		up.tmdbSearch = '';
		up.tmdbResults = null;
		up.title = r.title;
	}

	function toggleUploadTag(name: string) {
		up.tags = up.tags.includes(name) ? up.tags.filter((n) => n !== name) : [...up.tags, name];
	}

	function addUploadTag() {
		const name = up.tagInput.trim();
		if (!name) return;
		if (!up.tags.includes(name)) up.tags = [...up.tags, name];
		up.tagInput = '';
	}

	const uploadTagChoices = $derived([...new Set([...knownTags.map((t) => t.name), ...up.tags])]);

	async function submitUpload() {
		if (up.busy) return;
		if (!up.file) return showToast('Choose a trailer file first', 'error');
		const title = up.title.trim();
		if (!up.tmdb && !title) return showToast('Enter a title or link a TMDB movie', 'error');
		const fields: Record<string, string> = {};
		if (title) fields.title = title;
		if (up.tmdb) fields.tmdbid = String(up.tmdb.tmdbid);
		if (up.tags.length) fields.tags = up.tags.join(',');

		up.busy = true;
		up.pct = 0;
		const file = up.file;
		await act('Upload failed', async () => {
			await uploadWithProgress(
				'/api/v2/trailers/upload',
				file,
				fields,
				(e) => (up.pct = e.percent)
			);
			showToast(`Trailer "${title || up.tmdb!.title}" uploaded`, 'success');
			fetchOpen = false;
			changed();
		});
		up.busy = false;
	}
</script>

<svelte:window onkeydown={onWindowKeydown} />

{#snippet fact(label: string, value: string, cls: string)}
	<div class="flex justify-between gap-2">
		<dt class="text-muted">{label}</dt>
		<dd class={cls}>{value}</dd>
	</div>
{/snippet}

{#snippet fileLamp(t: Trailer)}
	{#if t.file_exists}
		<StatusLamp colour="green" quiet>On disk</StatusLamp>
	{:else}
		<StatusLamp colour="amber">Missing</StatusLamp>
	{/if}
{/snippet}

{#snippet link(text: string | number, onclick: (e: Event) => void, title?: string)}
	<button type="button" class="hover:text-accent" {title} {onclick}>{text}</button>
{/snippet}

<!-- A fact on a card that narrows the list to it. -->
{#snippet facet(text: string | number, set: () => void, title: string)}
	{@render link(
		text,
		stop(() => filterBy(set)),
		title
	)}
{/snippet}

{#snippet playButton(t: Trailer, cls: string)}
	<button
		type="button"
		class="{cls} text-muted hover:text-accent disabled:opacity-40"
		title="Play"
		disabled={!t.file_exists}
		onclick={stop(() => openDetail(t.id, true))}
	>
		<Play size={13} />
	</button>
{/snippet}

{#snippet head(cols: string[])}
	<thead>
		<tr class="border-b border-border bg-surface-2 text-left font-medium text-muted">
			{#each cols as c (c)}<th class="px-2 py-1.5">{c}</th>{/each}
		</tr>
	</thead>
{/snippet}

{#snippet deleteButton(t: Trailer)}
	<button
		type="button"
		class="rounded-sm p-1 text-faint hover:text-danger"
		title="Remove"
		aria-label="Delete"
		onclick={stop(() => void deleteTrailer(t))}
	>
		<Trash2 size={13} />
	</button>
{/snippet}

{#snippet poster(r: TmdbResult, cls: string, icon: number)}
	{#if r.poster_url}
		<img src={r.poster_url} alt="" loading="lazy" class="{cls} shrink-0 rounded-xs object-cover" />
	{:else}
		<span
			class="flex {cls} shrink-0 items-center justify-center rounded-xs bg-surface-3 text-faint"
		>
			<Film size={icon} />
		</span>
	{/if}
{/snippet}

<ConfirmDialog bind:this={confirmDialog} confirmLabel="Delete" />

<PageHeader title="Trailer library" {actions} />
{#snippet actions()}
	<Button
		onclick={() => (matchOpen = true)}
		title="See which trailers a trailer rule would pick for a movie"
	>
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
{/snippet}

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
		onchange: on((v: string) => (q = v))
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
			<ErrorState error={loadError} retry={() => void loadLibrary('reset')} />
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
							if (e.key !== 'Enter' && e.key !== ' ') return;
							e.preventDefault();
							openDetail(t.id);
						}}
					>
						<div class="mb-2 flex items-center justify-between gap-2">
							{@render playButton(t, 'rounded-md border border-border-strong bg-surface-2 p-1.5')}
							<button
								type="button"
								class="font-mono text-xs {t.content_rating && t.rating_ok
									? 'text-muted hover:text-accent'
									: 'text-warning'}"
								title={!t.content_rating
									? 'No rating'
									: t.rating_ok
										? 'Show this rating only'
										: 'Rating not in configured set - click to show'}
								onclick={stop(
									() => t.content_rating && filterBy(() => (rating = t.content_rating!))
								)}
							>
								{t.content_rating ? `${t.content_rating}${t.rating_ok ? '' : ' !'}` : 'no rating'}
							</button>
						</div>
						<p class="truncate text-sm font-medium group-hover:text-accent" title={t.title}>
							{t.title}
						</p>
						<p class="truncate text-xs text-muted">
							{#if t.year}
								{@render facet(t.year, () => (year = t.year), `Show ${t.year} trailers`)}
							{/if}
							{#if t.director}
								{t.year ? ' · ' : ''}{@render facet(
									t.director,
									() => (q = t.director!),
									`Show trailers by ${t.director}`
								)}
							{/if}
						</p>
						<p class="truncate text-xs text-faint">
							{#each (t.genres ?? []).slice(0, 3) as g, i (g)}
								{i ? ' · ' : ''}{@render facet(g, () => (genre = g), `Show ${g} trailers`)}
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
										onclick={stop(() => filterBy(() => (tag = String(tg.id))))}
									>
										<Tag size={9} />{tg.name}
									</button>
								{/each}
							</p>
						{/if}
						<div class="mt-2 flex items-center justify-between">
							{@render fileLamp(t)}
							{@render deleteButton(t)}
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
									checked={selected.allVisible}
									onchange={(e) =>
										e.currentTarget.checked ? selected.setVisible(true) : selected.clear()}
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
										onchange={(e) => selected.set(t.id, e.currentTarget.checked)}
									/>
								</td>
								<td class="px-3 py-1.5">{@render playButton(t, 'rounded-sm p-1')}</td>
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
								<td class="px-3 py-1.5 font-mono text-xs whitespace-nowrap text-muted">
									{t.duration ? formatTime(t.duration) : ''}
								</td>
								<td class="px-3 py-1.5 font-mono text-xs whitespace-nowrap text-muted">
									{formatSize(t.file_size)}
								</td>
								<td class="max-w-56 truncate px-3 py-1.5 text-xs text-muted">
									{(t.genres ?? []).join(', ')}
									{#if t.trailer_tags?.length}
										<span class="text-faint">
											[{t.trailer_tags.map((tg) => tg.name).join(', ')}]
										</span>
									{/if}
								</td>
								<td class="px-3 py-1.5">{@render fileLamp(t)}</td>
								<td class="px-3 py-1.5">{@render deleteButton(t)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}

		{#if !loading && !loadError && offset < total}
			<div class="mt-4 text-center">
				<Button disabled={loadingMore} onclick={() => void loadLibrary('more')}>
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
				{#if t.file_exists}
					<!-- svelte-ignore a11y_media_has_caption -->
					<video
						src={t.stream_url}
						controls
						{autoplay}
						onplay={() => (autoplay = false)}
						preload="metadata"
						class="mt-3 max-h-[52vh] w-full bg-black"
					></video>
				{:else}
					<p
						class="mt-3 flex items-center gap-2 border border-warning/40 bg-surface-2 px-3 py-2 text-sm text-warning"
					>
						<TriangleAlert size={15} /> The file is missing on disk - it can't be played.
					</p>
				{/if}
				<dl class="mt-4 space-y-2 text-sm">
					{#if t.year || t.month}
						<div class="flex justify-between gap-2">
							<dt class="text-muted">Year</dt>
							<dd>
								{#if t.year}{@render link(t.year, () => filterYear(t.year!))}{/if}{t.month
									? ` · month ${t.month}`
									: ''}
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
							<dd>{@render link(t.director, () => filterDirector(t.director!))}</dd>
						</div>
					{/if}
					{#if t.duration}{@render fact('Duration', `${Math.round(t.duration)}s`, 'font-mono')}{/if}
					{#if t.tmdbid}{@render fact('TMDB id', String(t.tmdbid), 'font-mono')}{/if}
					{#if t.rating_lookups?.[ratingsSystem]}
						{@render fact('Rating lookup', t.rating_lookups[ratingsSystem], 'min-w-0 truncate')}
					{/if}
					<div class="flex justify-between gap-2">
						<dt class="text-muted">Linked movie</dt>
						<dd class="min-w-0 truncate">
							{#if t.associated_movie}
								<a
									href="{base}/library?movie={t.associated_movie.id}"
									class="text-accent hover:underline"
									title="Open this film in the library"
									>{t.associated_movie.title} ({t.associated_movie.year ?? '-'})</a
								>
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
						<dd>{@render fileLamp(t)}</dd>
					</div>
				</dl>
				<p class="mt-4 font-mono text-[10px] break-all text-faint" title={t.file_path ?? ''}>
					{t.file_path ?? '-'}
				</p>
			{/if}
			{#snippet actions()}
				{#if detail}
					{@const t = detail}
					{#if t.tmdbid}
						<Button
							size="sm"
							disabled={job.active}
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
								{@render poster(r, 'h-12 w-8', 14)}
								<span class="min-w-0 flex-1">
									<span class="block truncate text-sm">{r.title}</span>
									<span class="font-mono text-xs text-muted">{r.year ?? ''}</span>
								</span>
								{#if r.in_library}<Badge>In library</Badge>{/if}
								{#if r.has_trailer}
									<StatusLamp colour="green">Trailer downloaded</StatusLamp>
									<Button
										size="sm"
										disabled={job.active}
										title="Pick a different video and replace the downloaded trailer"
										onclick={() => openVideoPicker(r.tmdbid, r.title, true)}
									>
										Replace…
									</Button>
								{:else}
									<Button
										size="sm"
										disabled={job.active}
										title="Choose which of the movie's videos to download"
										onclick={() => openVideoPicker(r.tmdbid, r.title, false)}
									>
										Choose…
									</Button>
									<Button
										size="sm"
										variant="primary"
										disabled={job.active}
										onclick={() => fetchSingle(r.tmdbid)}
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
		{#snippet discField(key: keyof typeof disc, label: string, choices?: [string, string][])}
			<div>
				<label class="mb-1 block text-xs text-muted" for="f{key}">{label}</label>
				{#if choices}
					<Select id="f{key}" bind:value={disc[key]} class="w-full">
						{#each choices as [value, text] (value)}<option {value}>{text}</option>{/each}
					</Select>
				{:else}
					<Input id="f{key}" type="number" bind:value={disc[key]} placeholder={DISC_HINTS[key]} />
				{/if}
			</div>
		{/snippet}
		<div class="grid grid-cols-2 gap-3 sm:grid-cols-3">
			{@render discField('YearFrom', 'Year from')}
			{@render discField('YearTo', 'Year to')}
			{@render discField('Limit', 'Limit')}
			{@render discField('Sort', 'Sort by', [
				['popularity.desc', 'Popularity (high - low)'],
				['popularity.asc', 'Popularity (low - high)'],
				['release_date.desc', 'Release date (newest)'],
				['release_date.asc', 'Release date (oldest)'],
				['vote_average.desc', 'Rating (high - low)']
			])}
			{@render discField('MinRating', 'Min TMDB rating')}
			{@render discField('Cert', 'Certification (GB)', [
				['', 'Any'],
				...['U', 'PG', '12A', '15', '18'].map((c): [string, string] => [c, c])
			])}
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
						{@render head(['Title', 'Year', 'Genres', 'Rating', 'Status'])}
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
				ondragover={onUploadDrag}
				ondragenter={onUploadDrag}
				ondragleave={onUploadDrag}
				ondrop={onUploadDrag}
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

			{#if up.file}
				<p class="flex items-center gap-2 text-xs text-muted">
					<Film size={13} />
					<span class="min-w-0 truncate" title={up.file.name}>{up.file.name}</span>
					<span class="shrink-0 font-mono">{(up.file.size / (1024 * 1024)).toFixed(1)} MB</span>
				</p>
			{/if}

			<div>
				<label class="mb-1 block text-xs text-muted" for="up.tmdbSearch">
					Link to TMDB <span class="text-faint">(optional)</span>
				</label>
				<Input
					id="up.tmdbSearch"
					bind:value={up.tmdbSearch}
					oninput={onTmdbSearchInput}
					placeholder="Search TMDB by title…"
				/>
				{#if up.tmdbResults !== null}
					<div class="mt-1 max-h-44 overflow-y-auto rounded-md border border-border bg-surface-2">
						{#if up.tmdbNoKey}
							<p class="px-3 py-2 text-xs text-muted">
								No TMDB API key configured -
								<a href="{base}/settings?tab=library" class="text-accent underline"
									>add one in Settings</a
								>
								to link uploads. Unlinked uploads work fine.
							</p>
						{:else if !up.tmdbResults.length}
							<p class="px-3 py-2 text-xs text-muted">No TMDB matches for "{up.tmdbSearch}"</p>
						{:else}
							{#each up.tmdbResults as r (r.tmdbid)}
								<button
									type="button"
									class="flex w-full items-center gap-2 px-2 py-1.5 text-left hover:bg-surface-3"
									onclick={() => selectTmdb(r)}
								>
									{@render poster(r, 'h-10 w-7', 12)}
									<span class="min-w-0 flex-1 truncate text-sm">{r.title}</span>
									<span class="shrink-0 font-mono text-xs text-muted">{r.year ?? ''}</span>
								</button>
							{/each}
						{/if}
					</div>
				{/if}
				{#if up.tmdb}
					<p class="mt-1.5 flex items-center gap-2 text-xs">
						<span class="min-w-0 truncate"
							>{up.tmdb.title}{up.tmdb.year ? ` (${up.tmdb.year})` : ''}</span
						>
						<Badge variant="accent"><LinkIcon size={9} /> TMDB {up.tmdb.tmdbid}</Badge>
						<button
							type="button"
							class="text-faint hover:text-danger"
							title="Clear TMDB link"
							aria-label="Clear TMDB link"
							onclick={() => (up.tmdb = null)}
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
				<label class="mb-1 block text-xs text-muted" for="up.title">Title</label>
				<Input id="up.title" bind:value={up.title} placeholder="Trailer title" />
			</div>

			<div>
				<span class="mb-1 block text-xs text-muted">Trailer tags</span>
				{#if uploadTagChoices.length}
					<div class="mb-1.5 flex flex-wrap gap-1">
						{#each uploadTagChoices as name (name)}
							{@const on = up.tags.includes(name)}
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
					bind:value={up.tagInput}
					onkeydown={(e) => {
						if (e.key === 'Enter') {
							e.preventDefault();
							addUploadTag();
						}
					}}
				/>
			</div>

			{#if up.busy}
				<div>
					<div class="h-1.5 overflow-hidden rounded-xs bg-surface-3">
						<div
							class="h-full bg-accent transition-[width]"
							style="width: {Math.round(up.pct)}%"
						></div>
					</div>
					<p class="mt-1 text-xs text-muted">
						{up.pct >= 100 ? 'Processing…' : `${Math.round(up.pct)}%`}
					</p>
				</div>
			{/if}
		</div>
		<div class="mt-3">
			<Button size="sm" variant="primary" disabled={up.busy} onclick={submitUpload}>
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
		<Button
			size="sm"
			variant="primary"
			onclick={() => job.start(() => api.POST('/api/v2/trailers/verify'))}>Run verify</Button
		>
	{:else}
		<p class="mb-3 text-sm text-muted">
			Looks up certificates for <strong class="text-text">trailers</strong> that have none yet - or one
			from a different scheme (e.g. an MPAA rating on a BBFC install) - directly from the classification
			body (bbfc.co.uk / filmratings.com). Movies are rated separately, from the library's sync panel.
		</p>
		<Button
			size="sm"
			variant="primary"
			onclick={() =>
				job.start(() =>
					api.POST('/api/v2/trailers/ratings/update', { body: { scope: 'trailers' } })
				)}>Update certificate ratings</Button
		>
	{/if}

	{#if job.job}
		<div class="mt-4"><JobProgress {job} opLabels={OP_LABEL} /></div>
	{/if}
</Dialog>

<Dialog
	bind:open={vpOpen}
	title={vp.replace ? `Replace trailer - ${vp.title}` : `Choose video - ${vp.title}`}
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
		{#if vp.replace}
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
							{#if v.official}<Badge variant="accent">Official</Badge>{/if}
							{#if v.size}<span class="font-mono">{v.size}p</span>{/if}
							{#if v.published_at}<span class="font-mono">{v.published_at.slice(0, 10)}</span>{/if}
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
					<Button size="sm" variant="primary" disabled={job.active} onclick={() => fetchVideo(v)}>
						<Download size={13} />
						{vp.replace ? 'Replace' : 'Download'}
					</Button>
				</li>
			{/each}
		</ul>
	{/if}
</Dialog>

<Dialog bind:open={bulkTagOpen} title="Tag selected trailers">
	<p class="mb-3 text-sm text-muted">
		Apply one tag to {plural(selected.size, 'selected trailer')}.
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
		{#each knownTags as t (t.id)}<option value={t.name}></option>{/each}
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
					{@render head(['Title', 'Change'])}
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
							{#if mt.will_play}<StatusLamp colour="green">Would play</StatusLamp>{/if}
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
