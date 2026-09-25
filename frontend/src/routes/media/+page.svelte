<script lang="ts">
	import { base } from '$app/paths';
	import { SvelteSet } from 'svelte/reactivity';
	import {
		ChevronLeft,
		ChevronRight,
		CloudUpload,
		Download,
		FilterX,
		Film,
		FolderOpen,
		Images,
		Music,
		Pencil,
		Play,
		Plus,
		RotateCw,
		Trash2,
		TriangleAlert,
		Upload,
		X
	} from '@lucide/svelte';
	import { api, toApiError, unwrap } from '$lib/api/client';
	import { Query } from '$lib/api/query.svelte';
	import { uploadWithProgress } from '$lib/upload';
	import { showToast as toast } from '$lib/toast.svelte';
	import { formatTime } from '$lib/format';
	import type { components } from '$lib/api/types.gen';
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
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import DetailPanel from '$lib/components/DetailPanel.svelte';
	import FilterBar from '$lib/components/FilterBar.svelte';
	import TagInput from '$lib/components/TagInput.svelte';
	import TagBadge from '$lib/components/TagBadge.svelte';
	import MediaTagBar from '$lib/media/MediaTagBar.svelte';
	import SortHeader from '$lib/components/SortHeader.svelte';

	type MediaItem = components['schemas']['MediaItemSchema'];
	type MediaCreated = components['schemas']['MediaCreateDataSchema'];
	type YouTubeProgress = components['schemas']['YouTubeProgressDataSchema'];
	type TagFacet = components['schemas']['TagSchema'];

	// Schema collapses two "PaginationSchema" backends; pin the runtime shape (media/schemas.py).
	interface MediaPagination {
		page: number;
		per_page: number;
		total: number;
		total_pages: number;
		has_previous: boolean;
		has_next: boolean;
	}
	interface MediaList {
		media: MediaItem[];
		pagination: MediaPagination;
		filters: { tags: string[]; tag_facets: TagFacet[] };
	}

	const AUDIO_FORMATS: [string, string][] = [
		['dolby_digital', 'Dolby Digital'],
		['dolby_truehd', 'Dolby TrueHD'],
		['dolby_atmos', 'Dolby Atmos'],
		['dts', 'DTS'],
		['dts_hd', 'DTS-HD'],
		['dts_x', 'DTS:X']
	];

	function audioFormatLabel(key: string | null | undefined): string {
		return AUDIO_FORMATS.find(([k]) => k === key)?.[1] ?? '';
	}

	function fmtDuration(seconds: number | null | undefined): string {
		const s = Math.round(Number(seconds) || 0);
		return s ? formatTime(s) : '';
	}

	function fmtSize(bytes: number | null | undefined): string {
		const b = Number(bytes) || 0;
		if (b === 0) return '';
		const k = 1024;
		const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
		const i = Math.min(sizes.length - 1, Math.floor(Math.log(b) / Math.log(k)));
		return `${parseFloat((b / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
	}

	function fmtDate(iso: string | null | undefined): string {
		if (!iso) return '-';
		const d = new Date(iso);
		return isNaN(d.getTime())
			? '-'
			: d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
	}

	function fileExists(m: MediaItem): boolean {
		return m.file_info.exists !== false;
	}
	function isAudio(m: MediaItem): boolean {
		return (m.file_info.mime_type ?? '').startsWith('audio');
	}
	function subLine(m: MediaItem): string {
		return [fmtDuration(m.duration), fmtSize(m.file_info.size), audioFormatLabel(m.audio_format)]
			.filter(Boolean)
			.join(' · ');
	}

	const PER_PAGE = 60;
	let search = $state('');
	let tags = $state<string[]>([]);
	let page = $state(1);
	let sort = $state('');
	let view = $state<'grid' | 'list'>(
		localStorage.getItem('media_view') === 'list' ? 'list' : 'grid'
	);
	let thumbVersion = $state(0);

	const media = new Query<MediaList>(async () => {
		const params: Record<string, string | number> = { page, per_page: PER_PAGE };
		if (search) params.search = search;
		if (tags.length) params.tags = tags.join(',');
		if (sort) {
			params.sort = sort.startsWith('-') ? sort.slice(1) : sort;
			params.order = sort.startsWith('-') ? 'desc' : 'asc';
		}
		return (await unwrap(
			api.GET('/api/v2/media/list', { params: { query: params } })
		)) as unknown as MediaList;
	});

	$effect(() => {
		void [search, tags, tags.length, page, sort];
		void media.load();
	});

	function headerSort(next: string) {
		sort = next;
		page = 1;
	}

	$effect(() => media.live());

	const items = $derived(media.data?.media ?? []);
	const pg = $derived(media.data?.pagination);
	const tagOptions = $derived(media.data?.filters.tags ?? []);
	const tagFacets = $derived(media.data?.filters.tag_facets ?? []);
	const filtersActive = $derived(Boolean(search) || tags.length > 0);

	function clearFilters() {
		search = '';
		tags = [];
		page = 1;
	}

	function setTagFilter(names: string[]) {
		tags = names;
		page = 1;
	}

	const countText = $derived.by(() => {
		const total = pg?.total ?? items.length;
		return `${total} ${total === 1 ? 'item' : 'items'}${filtersActive ? ' (filtered)' : ''}`;
	});

	// Per-item cache-buster: regenerating one item must not reload the whole wall.
	let thumbBustById = $state<Record<number, number>>({});
	function bust(url: string, id: number): string {
		const v = thumbBustById[id] ?? thumbVersion;
		return v ? `${url}?v=${v}` : url;
	}

	function hideBrokenImg(e: Event) {
		(e.currentTarget as HTMLImageElement).style.display = 'none';
	}

	let confirmDialog = $state<ConfirmDialog>();

	async function askConfirm(message: string, label: string, action: () => void) {
		if (await confirmDialog!.confirm(message, { confirmLabel: label })) action();
	}

	const picked = new SvelteSet<number>();
	let anchorId: number | null = null; // shift-click range anchor

	const allVisiblePicked = $derived(items.length > 0 && items.every((m) => picked.has(m.id)));

	function setPicked(id: number, on: boolean) {
		if (on) picked.add(id);
		else picked.delete(id);
	}

	function togglePicked(id: number, on: boolean, shift: boolean) {
		if (shift && anchorId !== null && anchorId !== id) {
			const a = items.findIndex((m) => m.id === anchorId);
			const b = items.findIndex((m) => m.id === id);
			if (a !== -1 && b !== -1) {
				for (let i = Math.min(a, b); i <= Math.max(a, b); i++) setPicked(items[i].id, on);
				anchorId = id;
				return;
			}
		}
		setPicked(id, on);
		anchorId = id;
	}

	function toggleAllVisible(on: boolean) {
		items.forEach((m) => setPicked(m.id, on));
		anchorId = null;
	}

	function clearPicked() {
		picked.clear();
		anchorId = null;
	}

	let selectedId = $state<number | null>(null);
	const selected = $derived(items.find((m) => m.id === selectedId) ?? null);

	function openDetail(id: number) {
		if (id !== selectedId) editing = false;
		selectedId = id;
	}
	function closeDetail() {
		selectedId = null;
		editing = false;
	}

	// Editing happens in the detail drawer itself: Edit swaps its body for the form.
	let editing = $state(false);
	let editItem = $state<MediaItem | null>(null);
	let editTitle = $state('');
	let editTags = $state<string[]>([]);
	let editAudioFormat = $state('');
	let editBusy = $state(false);
	let editTagInput = $state<TagInput>();

	function openEdit(m: MediaItem) {
		editItem = m;
		editTitle = m.title;
		editTags = m.tags.map((t) => t.name);
		editAudioFormat = m.audio_format ?? '';
		editing = true;
	}

	// Escape backs out of the form before it closes the drawer.
	function onEditKeydown(e: KeyboardEvent) {
		if (e.key !== 'Escape' || !editing || document.querySelector('dialog[open]')) return;
		e.preventDefault();
		editing = false;
	}

	async function saveEdit() {
		if (!editItem) return;
		editTagInput?.commit();
		editBusy = true;
		try {
			await unwrap(
				api.PUT('/api/v2/media/{media_id}', {
					params: { path: { media_id: editItem.id } },
					body: { title: editTitle.trim(), tag_names: editTags, audio_format: editAudioFormat }
				})
			);
			toast('Media updated', 'success');
			editing = false;
			await media.refresh();
		} catch (e) {
			toast(toApiError(e).message || 'Failed to update media', 'error');
		} finally {
			editBusy = false;
		}
	}

	function askRemove(m: MediaItem) {
		askConfirm(
			`Delete “${m.title}” from the library? (The file on disk is left untouched.)`,
			'Delete',
			() => void remove(m.id)
		);
	}

	async function remove(id: number) {
		try {
			await api.DELETE('/api/v2/media/{media_id}', { params: { path: { media_id: id } } });
			toast('Media removed', 'success');
			if (selectedId === id) closeDetail();
			await media.refresh();
		} catch (e) {
			toast(toApiError(e).message || 'Failed to delete media', 'error');
		}
	}

	let rethumbBusy = $state(false);
	let rethumbItemBusy = $state<number | null>(null);

	function askRegenerateAll() {
		askConfirm(
			'Regenerate thumbnails for every video in the media library?',
			'Regenerate',
			() => void regenerateThumbnails(null)
		);
	}

	async function regenerateThumbnails(mediaId: number | null) {
		if (mediaId === null) rethumbBusy = true;
		else rethumbItemBusy = mediaId;
		try {
			const res = await api.POST('/api/v2/media/thumbnails/regenerate', {
				params: { query: mediaId === null ? {} : { media_id: mediaId } }
			});
			if (res.error !== undefined || !res.data) throw toApiError(res.error, res.response);
			toast(res.data.message || 'Thumbnails regenerated', 'success');
			// Cache-bust so the fresh frames actually show — but only the item
			// that changed, not every tile in the grid.
			if (mediaId === null) thumbVersion = Date.now();
			else thumbBustById = { ...thumbBustById, [mediaId]: Date.now() };
			void media.refresh();
		} catch (e) {
			toast(toApiError(e).message || 'Could not regenerate thumbnails', 'error');
		} finally {
			rethumbBusy = false;
			rethumbItemBusy = null;
		}
	}

	interface UploadEntry {
		file: File;
		status: 'pending' | 'uploading' | 'done' | 'error';
		pct: number;
		error: string | null;
	}

	type AddMode = 'upload' | 'youtube' | 'path';
	const ADD_MODES: { mode: AddMode; label: string; submit: string }[] = [
		{ mode: 'upload', label: 'Upload file', submit: 'Upload' },
		{ mode: 'youtube', label: 'YouTube', submit: 'Download' },
		{ mode: 'path', label: 'Server path', submit: 'Add' }
	];

	let addOpen = $state(false);
	let addMode = $state<AddMode>('upload');
	let uploads = $state<UploadEntry[]>([]);
	let uploading = $state(false);
	let addBusy = $state(false);
	let dragOver = $state(false);
	let addTitle = $state('');
	let addTags = $state<string[]>([]);
	let addAudioFormat = $state('');
	let addTagInput = $state<TagInput>();
	let ytUrl = $state('');
	let pathInput = $state('');
	let addProgress = $state<{ pct: number; label: string } | null>(null);
	let fileInput = $state<HTMLInputElement>();

	function openAdd() {
		addMode = 'upload';
		uploads = [];
		uploading = false;
		addBusy = false;
		addTitle = '';
		addTags = [];
		addAudioFormat = '';
		ytUrl = '';
		pathInput = '';
		addProgress = null;
		addOpen = true;
	}

	function setAddMode(mode: AddMode) {
		addMode = mode;
		addProgress = null;
		syncTitleField();
	}

	// A batch always titles each file from its own name; a single file uses the title field.
	const batchUpload = $derived(addMode === 'upload' && uploads.length > 1);
	function syncTitleField() {
		if (batchUpload) addTitle = '';
		else if (addMode === 'upload' && uploads.length === 1 && !addTitle.trim()) {
			addTitle = uploads[0].file.name.replace(/\.[^.]+$/, '');
		}
	}

	function pickFiles(fileList: FileList | null | undefined) {
		const files = [...(fileList ?? [])];
		if (!files.length || uploading) return;
		for (const file of files) {
			const dup = uploads.some((u) => u.file.name === file.name && u.file.size === file.size);
			if (!dup) uploads.push({ file, status: 'pending', pct: 0, error: null });
		}
		syncTitleField();
	}

	function removeUpload(i: number) {
		if (uploading) return;
		uploads.splice(i, 1);
		syncTitleField();
	}

	async function applyAudioFormat(mediaId: number | null | undefined) {
		if (!mediaId || !addAudioFormat) return;
		try {
			await unwrap(
				api.PUT('/api/v2/media/{media_id}', {
					params: { path: { media_id: mediaId } },
					body: { audio_format: addAudioFormat }
				})
			);
		} catch (e) {
			console.error('Could not set audio format:', e);
		}
	}

	function finishAdd(msg: string) {
		toast(msg, 'success');
		addOpen = false;
		page = 1;
		void media.refresh();
	}

	async function submitAdd() {
		addTagInput?.commit();
		if (addMode === 'upload') {
			await submitUploadBatch();
		} else if (addMode === 'youtube') {
			const url = ytUrl.trim();
			if (!url) {
				toast('Enter a YouTube URL', 'error');
				return;
			}
			addBusy = true;
			addProgress = { pct: 0, label: 'Starting…' };
			try {
				const data = await unwrap(
					api.POST('/api/v2/media/youtube-download', {
						body: { url, title: addTitle.trim() || null, tag_names: addTags }
					})
				);
				await monitorYoutube(data.task_id);
			} catch (e) {
				toast(toApiError(e).message || 'Failed to add media', 'error');
				addBusy = false;
				addProgress = null;
			}
		} else {
			const path = pathInput.trim();
			if (!path) {
				toast('Enter a file path', 'error');
				return;
			}
			if (!addTitle.trim()) {
				toast('Enter a title', 'error');
				return;
			}
			addBusy = true;
			try {
				const created = await unwrap(
					api.POST('/api/v2/media/create', {
						body: { file_path: path, title: addTitle.trim(), tag_names: addTags }
					})
				);
				await applyAudioFormat((created as MediaCreated).id);
				finishAdd('Media added');
			} catch (e) {
				toast(toApiError(e).message || 'Failed to add media', 'error');
			} finally {
				addBusy = false;
			}
		}
	}

	// Keeps polling even if the modal is closed meanwhile.
	async function monitorYoutube(taskId: string) {
		for (;;) {
			await new Promise((r) => setTimeout(r, 1000));
			let prog: YouTubeProgress;
			try {
				prog = await unwrap(
					api.GET('/api/v2/media/youtube-progress/{task_id}', {
						params: { path: { task_id: taskId } }
					})
				);
			} catch (e) {
				toast(toApiError(e).message || 'YouTube download failed', 'error');
				break;
			}
			if (prog.status === 'failed') {
				toast(prog.error || 'YouTube download failed', 'error');
				break;
			}
			if (prog.status === 'completed') {
				await applyAudioFormat(prog.media_id);
				finishAdd('Downloaded from YouTube');
				break;
			}
			const pct = prog.progress ?? 0;
			addProgress = { pct, label: `Downloading ${Math.round(pct)}%` };
		}
		addBusy = false;
		addProgress = null;
	}

	// Failed files stay queued for a retry; the modal only closes when everything succeeded.
	async function submitUploadBatch() {
		const todo = uploads.filter((u) => u.status !== 'done');
		if (!todo.length) {
			toast('Choose a video or audio file first', 'error');
			return;
		}
		uploading = true;

		let ok = 0;
		let failed = 0;
		for (const u of todo) {
			u.status = 'uploading';
			u.pct = 0;
			u.error = null;
			try {
				const fileTitle =
					uploads.length === 1 && addTitle.trim()
						? addTitle.trim()
						: u.file.name.replace(/\.[^.]+$/, '');
				const created = await uploadWithProgress<MediaCreated>(
					'/api/v2/media/upload',
					u.file,
					{ title: fileTitle, tag_names: addTags.join(',') },
					(e) => (u.pct = e.percent)
				);
				u.status = 'done';
				u.pct = 100;
				await applyAudioFormat(created.id);
				ok++;
			} catch (e) {
				console.error(`Upload failed for ${u.file.name}:`, e);
				u.status = 'error';
				u.error = toApiError(e).message || 'Upload failed';
				failed++;
			}
		}

		uploading = false;
		if (ok) {
			page = 1;
			void media.refresh();
		}
		if (!failed) {
			toast(ok === 1 ? 'Media uploaded' : `Uploaded ${ok} files`, 'success');
			addOpen = false;
		} else {
			toast(`${failed} of ${ok + failed} uploads failed - press Upload to retry them`, 'error');
		}
	}

	function uploadStateLabel(u: UploadEntry): string {
		switch (u.status) {
			case 'uploading':
				return u.pct >= 100 ? 'Processing…' : `${Math.round(u.pct)}%`;
			case 'done':
				return 'Done';
			case 'error':
				return 'Failed';
			default:
				return 'Queued';
		}
	}
</script>

<svelte:head><title>User media - Cinefin</title></svelte:head>
<svelte:window onkeydowncapture={onEditKeydown} />

<div class="mb-1 flex flex-wrap items-center gap-2">
	<h1 class="mr-auto text-lg font-semibold">User media</h1>
	<Button
		onclick={askRegenerateAll}
		disabled={rethumbBusy}
		title="Re-extract the screenshot thumbnails from every video"
	>
		<RotateCw size={14} /> Regenerate thumbnails
	</Button>
	<Button variant="primary" onclick={openAdd}><Plus size={14} /> Add media</Button>
</div>

<p class="mb-4 text-sm text-muted">
	Theater idents, audio-format intros and the other clips used as programme building blocks. Movies
	live in the <a href="{base}/library" class="text-accent hover:underline">Library</a>, trailers in
	the <a href="{base}/trailers" class="text-accent hover:underline">Trailer library</a>.
</p>

<FilterBar
	search={{
		value: search,
		placeholder: 'Search by title…',
		onchange: (v) => {
			search = v;
			page = 1;
		}
	}}
	count={countText}
	bind:view
	viewKey="media_view"
	onreset={clearFilters}
/>

<MediaTagBar
	tags={tagFacets}
	filter={tags}
	onfilter={setTagFilter}
	picked={items.filter((m) => picked.has(m.id))}
	onchanged={() => media.refresh()}
	onclearpick={clearPicked}
	confirm={(msg, opts) => confirmDialog!.confirm(msg, opts)}
/>

{#if media.loading}
	<Spinner label="Loading media…" />
{:else if media.error}
	<ErrorState error={media.error} retry={() => void media.load()} />
{:else if !items.length}
	{#if filtersActive}
		<EmptyState
			icon={FilterX}
			title="No matching media"
			message="No clips match your search or tag filters. Try different terms, or clear the filters to see the whole library."
		>
			{#snippet action()}
				<Button onclick={clearFilters}>Clear filters</Button>
			{/snippet}
		</EmptyState>
	{:else}
		<EmptyState
			icon={Images}
			title="No media yet"
			message="Upload a clip, fetch one from YouTube, or import a file already on the server to build your user media library."
		>
			{#snippet action()}
				<Button variant="primary" onclick={openAdd}><Plus size={14} /> Add media</Button>
			{/snippet}
		</EmptyState>
	{/if}
{:else if view === 'grid'}
	<!-- Auto-fill, not breakpoints: the detail drawer takes width from this grid when docked. -->
	<div class="grid grid-cols-[repeat(auto-fill,minmax(8.5rem,1fr))] gap-4">
		{#each items as m (m.id)}
			{@const exists = fileExists(m)}
			<div
				class="group {exists ? '' : 'opacity-70'}"
				data-panel-item={m.id}
				data-panel-current={m.id === selectedId || undefined}
			>
				<div
					class="relative aspect-video overflow-hidden rounded-md border bg-surface-2
					{picked.has(m.id) ? 'border-accent' : 'border-border'}"
				>
					<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions, a11y_no_noninteractive_element_interactions -->
					<label
						class="absolute top-1 left-1 z-10 flex h-5 w-5 items-center justify-center rounded-sm
						border border-border-strong bg-bg/80 transition-opacity
						{picked.has(m.id) ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'}"
						onclick={(e) => e.stopPropagation()}
					>
						<input
							type="checkbox"
							class="accent-accent"
							checked={picked.has(m.id)}
							onclick={(e) => {
								const ev = e as MouseEvent;
								togglePicked(m.id, (e.currentTarget as HTMLInputElement).checked, ev.shiftKey);
							}}
						/>
					</label>
					<button
						type="button"
						class="block h-full w-full cursor-pointer"
						onclick={() => openDetail(m.id)}
						title={m.title || 'Untitled'}
					>
						{#if exists && m.screenshot_url}
							<img
								src={bust(m.screenshot_url, m.id)}
								alt=""
								loading="lazy"
								onerror={hideBrokenImg}
								class="h-full w-full object-cover transition-opacity group-hover:opacity-80"
							/>
						{:else}
							<span class="flex h-full w-full items-center justify-center text-faint">
								{#if !exists}<TriangleAlert size={22} class="text-warning" />
								{:else if isAudio(m)}<Music size={22} />
								{:else}<Film size={22} />{/if}
							</span>
						{/if}
						{#if exists}
							<span
								class="pointer-events-none absolute inset-0 flex items-center justify-center bg-black/40 text-text opacity-0 transition-opacity group-hover:opacity-100"
							>
								<Play size={22} />
							</span>
						{/if}
					</button>
					{#if fmtDuration(m.duration)}
						<span
							class="pointer-events-none absolute bottom-1 left-1 rounded-sm bg-bg/80 px-1 font-mono text-[0.65rem] text-muted"
						>
							{fmtDuration(m.duration)}
						</span>
					{/if}
					{#if !exists}
						<span class="pointer-events-none absolute bottom-1 right-1">
							<Badge variant="warning">file missing</Badge>
						</span>
					{/if}
				</div>
				<p class="mt-1.5 truncate text-sm" title={m.file_path}>{m.title || 'Untitled'}</p>
				<p class="truncate text-xs text-muted">{subLine(m) || '-'}</p>
			</div>
		{/each}
	</div>
{:else}
	<div class="overflow-x-auto border border-border">
		<table class="w-full text-sm">
			<thead>
				<tr class="border-b border-border bg-surface-2 text-left text-xs font-medium text-muted">
					<th class="w-8 px-3 py-2">
						<input
							type="checkbox"
							class="accent-accent"
							aria-label="Select all shown"
							checked={allVisiblePicked}
							onchange={(e) => toggleAllVisible((e.currentTarget as HTMLInputElement).checked)}
						/>
					</th>
					<th class="w-20 px-3 py-2"></th>
					<SortHeader {sort} col="title" label="Title" onsort={headerSort} />
					<th class="px-3 py-2">Tags</th>
					<SortHeader {sort} col="duration" label="Duration" defaultDesc onsort={headerSort} />
					<SortHeader {sort} col="file_size" label="Size" defaultDesc onsort={headerSort} />
					<SortHeader {sort} col="audio_format" label="Audio" onsort={headerSort} />
					<SortHeader {sort} col="upload_date" label="Uploaded" defaultDesc onsort={headerSort} />
				</tr>
			</thead>
			<tbody class="divide-y divide-border">
				{#each items as m (m.id)}
					{@const exists = fileExists(m)}
					<tr
						class="cursor-pointer hover:bg-surface-2 {exists ? '' : 'opacity-70'}
						{picked.has(m.id) ? 'bg-surface-2' : ''}"
						data-panel-item={m.id}
						data-panel-current={m.id === selectedId || undefined}
						onclick={() => openDetail(m.id)}
					>
						<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
						<td class="px-3 py-1.5" onclick={(e) => e.stopPropagation()}>
							<input
								type="checkbox"
								class="accent-accent"
								aria-label="Select {m.title || 'item'}"
								checked={picked.has(m.id)}
								onclick={(e) => {
									const ev = e as MouseEvent;
									togglePicked(m.id, (e.currentTarget as HTMLInputElement).checked, ev.shiftKey);
								}}
							/>
						</td>
						<td class="px-3 py-1.5">
							{#if exists && m.screenshot_url}
								<img
									src={bust(m.screenshot_url, m.id)}
									alt=""
									loading="lazy"
									onerror={hideBrokenImg}
									class="h-9 w-16 rounded-sm border border-border object-cover"
								/>
							{:else}
								<span
									class="flex h-9 w-16 items-center justify-center rounded-sm border border-border bg-surface-2 text-faint"
								>
									{#if !exists}<TriangleAlert size={14} class="text-warning" />
									{:else if isAudio(m)}<Music size={14} />
									{:else}<Film size={14} />{/if}
								</span>
							{/if}
						</td>
						<td class="px-3 py-1.5" title={m.file_path}>
							{m.title || 'Untitled'}
							{#if !exists}<StatusLamp colour="amber" class="ml-1.5">File missing</StatusLamp>{/if}
						</td>
						<td class="px-3 py-1.5">
							{#if m.tags.length}
								<div class="flex flex-wrap gap-1">
									{#each m.tags as t (t.id)}
										<TagBadge color={t.color}>{t.name}</TagBadge>
									{/each}
								</div>
							{:else}
								<span class="text-muted">-</span>
							{/if}
						</td>
						<td class="px-3 py-1.5 text-right font-mono text-xs"
							>{fmtDuration(m.duration) || '-'}</td
						>
						<td class="px-3 py-1.5 text-right font-mono text-xs"
							>{fmtSize(m.file_info.size) || '-'}</td
						>
						<td class="px-3 py-1.5 text-muted">{audioFormatLabel(m.audio_format) || '-'}</td>
						<td class="px-3 py-1.5 whitespace-nowrap text-muted">{fmtDate(m.upload_date)}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{/if}

{#if !media.loading && !media.error && items.length}
	<div class="mt-6 flex items-center justify-between gap-3">
		<p class="text-sm text-muted">Showing {items.length} of {pg?.total ?? items.length}</p>
		{#if (pg?.total_pages ?? 1) > 1}
			<div class="flex items-center gap-2">
				<Button
					size="sm"
					disabled={!pg?.has_previous}
					onclick={() => (page = Math.max(1, page - 1))}
				>
					<ChevronLeft size={14} /> Prev
				</Button>
				<span class="font-mono text-xs text-muted">{pg?.page} / {pg?.total_pages}</span>
				<Button size="sm" disabled={!pg?.has_next} onclick={() => (page = page + 1)}>
					Next <ChevronRight size={14} />
				</Button>
			</div>
		{/if}
	</div>
{/if}

{#if selectedId !== null}
	<DetailPanel
		label={selected?.title || 'Media item'}
		ids={items.map((m) => m.id)}
		currentId={selectedId}
		onclose={closeDetail}
		onstep={(id) => openDetail(id)}
	>
		{#if selected}
			{@const m = selected}
			<h2 class="text-xl leading-tight font-semibold">{m.title || 'Untitled'}</h2>

			{#if editing}
				<div class="mt-4">
					<div class="space-y-4">
						<div>
							<label class="mb-1 block text-sm text-muted" for="edit-title">Title</label>
							<Input id="edit-title" bind:value={editTitle} />
						</div>
						<div>
							<label class="mb-1 block text-sm text-muted" for="edit-tags-field">Tags</label>
							<TagInput
								bind:this={editTagInput}
								bind:tags={editTags}
								id="edit-tags-field"
								suggestions={tagOptions}
							/>
						</div>
						<div>
							<label class="mb-1 block text-sm text-muted" for="edit-audio-format"
								>Audio-format intro</label
							>
							<Select id="edit-audio-format" bind:value={editAudioFormat} class="w-full">
								<option value="">- Not an audio intro -</option>
								{#each AUDIO_FORMATS as [key, label] (key)}
									<option value={key}>{label}</option>
								{/each}
							</Select>
							<p class="mt-1 text-xs text-faint">
								Mark this clip as the intro for an audio format so it can auto-play before matching
								features.
							</p>
						</div>
					</div>
				</div>
			{:else}
				{#if fileExists(m)}
					<!-- svelte-ignore a11y_media_has_caption -- user clips carry no caption tracks -->
					<video
						src="/api/v2/media/{m.id}/download?inline=true"
						controls
						preload="metadata"
						class="mt-3 max-h-[52vh] w-full bg-black"
					></video>
				{:else}
					<p
						class="mt-3 flex items-center gap-2 border border-warning/40 bg-surface-2 px-3 py-2 text-sm text-warning"
					>
						<TriangleAlert size={15} /> The file is missing on disk - it can't be played or downloaded.
					</p>
				{/if}

				{#if m.tags.length}
					<div class="mt-4 flex flex-wrap gap-1.5">
						{#each m.tags as t (t.id)}
							<TagBadge color={t.color}>{t.name}</TagBadge>
						{/each}
					</div>
				{/if}

				<dl class="mt-4 space-y-1.5 text-sm">
					<div class="flex justify-between gap-4">
						<dt class="text-muted">Type</dt>
						<dd>{isAudio(m) ? 'Audio' : 'Video'}</dd>
					</div>
					{#if fmtDuration(m.duration)}
						<div class="flex justify-between gap-4">
							<dt class="text-muted">Duration</dt>
							<dd class="font-mono">{fmtDuration(m.duration)}</dd>
						</div>
					{/if}
					{#if fmtSize(m.file_info.size)}
						<div class="flex justify-between gap-4">
							<dt class="text-muted">Size</dt>
							<dd class="font-mono">{fmtSize(m.file_info.size)}</dd>
						</div>
					{/if}
					{#if audioFormatLabel(m.audio_format)}
						<div class="flex justify-between gap-4">
							<dt class="text-muted">Audio-format intro</dt>
							<dd>{audioFormatLabel(m.audio_format)}</dd>
						</div>
					{/if}
					<div class="flex justify-between gap-4">
						<dt class="shrink-0 text-muted">On disk</dt>
						<dd class="font-mono">{fileExists(m) ? 'Present' : 'Missing'}</dd>
					</div>
				</dl>

				{#if m.file_path}
					<p class="mt-4 font-mono text-[10px] break-all text-faint" title={m.file_path}>
						{m.file_path}
					</p>
				{/if}
			{/if}
		{/if}

		{#snippet actions()}
			{#if selected && editing}
				<Button onclick={() => (editing = false)}>Cancel</Button>
				<Button variant="primary" disabled={editBusy} onclick={() => void saveEdit()}>
					{editBusy ? 'Saving…' : 'Save'}
				</Button>
			{:else if selected}
				{@const m = selected}
				<Button onclick={() => askRemove(m)}><Trash2 size={14} /> Delete</Button>
				{#if !isAudio(m)}
					<Button
						onclick={() => void regenerateThumbnails(m.id)}
						disabled={rethumbItemBusy === m.id}
					>
						<RotateCw size={14} /> Regenerate thumbnail
					</Button>
				{/if}
				{#if fileExists(m)}
					<Button href="/api/v2/media/{m.id}/download"><Download size={14} /> Download</Button>
				{/if}
				<Button variant="primary" onclick={() => openEdit(m)}><Pencil size={14} /> Edit</Button>
			{/if}
		{/snippet}
	</DetailPanel>
{/if}

<Dialog bind:open={addOpen} title="Add media">
	<div class="space-y-4">
		<Tabs
			tabs={ADD_MODES.map(({ mode, label }) => ({ id: mode, label }))}
			value={addMode}
			label="How to add media"
			onselect={(id) => setAddMode(id as typeof addMode)}
		/>

		{#if addMode === 'upload'}
			<button
				type="button"
				class="flex w-full flex-col items-center gap-1.5 rounded-md border-2 border-dashed px-4 py-6 text-center
					{dragOver
					? 'border-accent bg-accent/5'
					: 'border-border-strong bg-surface-2 hover:border-accent-dim'}"
				onclick={() => fileInput?.click()}
				ondragover={(e) => {
					e.preventDefault();
					dragOver = true;
				}}
				ondragenter={(e) => {
					e.preventDefault();
					dragOver = true;
				}}
				ondragleave={(e) => {
					e.preventDefault();
					dragOver = false;
				}}
				ondrop={(e) => {
					e.preventDefault();
					dragOver = false;
					pickFiles(e.dataTransfer?.files);
				}}
			>
				<CloudUpload size={22} class="text-muted" />
				<span class="text-sm"
					><strong>Drag video or audio files here</strong> or click to browse</span
				>
				<span class="text-xs text-faint">
					Video clips or audio intros (Dolby/DTS stings, etc.) - drop several to upload a batch
				</span>
			</button>
			<input
				bind:this={fileInput}
				type="file"
				accept="video/*,audio/*"
				multiple
				hidden
				onchange={(e) => {
					const input = e.currentTarget as HTMLInputElement;
					pickFiles(input.files);
					input.value = '';
				}}
			/>

			{#if uploads.length}
				<div class="space-y-2">
					{#each uploads as u, i (u.file.name + u.file.size)}
						<div class="rounded-md border border-border bg-surface-2 p-2">
							<div class="flex items-center gap-2 text-xs">
								<span class="min-w-0 flex-1 truncate" title={u.file.name}>{u.file.name}</span>
								<span class="shrink-0 font-mono text-faint">{fmtSize(u.file.size)}</span>
								<span
									class="shrink-0 font-mono {u.status === 'done'
										? 'text-success'
										: u.status === 'error'
											? 'text-danger'
											: 'text-muted'}"
								>
									{uploadStateLabel(u)}
								</span>
								{#if (u.status === 'pending' || u.status === 'error') && !uploading}
									<button
										type="button"
										class="shrink-0 text-muted hover:text-danger"
										aria-label="Remove file"
										title="Remove"
										onclick={() => removeUpload(i)}
									>
										<X size={13} />
									</button>
								{/if}
							</div>
							<div class="mt-1.5 h-1 overflow-hidden rounded-xs bg-surface-3">
								<div
									class="h-full transition-[width] {u.status === 'error'
										? 'bg-danger'
										: 'bg-accent'}"
									style="width: {Math.round(u.pct)}%"
								></div>
							</div>
							{#if u.error}
								<p class="mt-1 text-xs text-danger">{u.error}</p>
							{/if}
						</div>
					{/each}
				</div>
			{/if}
		{:else if addMode === 'youtube'}
			<div>
				<label class="mb-1 block text-sm text-muted" for="yt-url">YouTube URL</label>
				<Input id="yt-url" bind:value={ytUrl} placeholder="https://www.youtube.com/watch?v=…" />
			</div>
		{:else}
			<div>
				<label class="mb-1 block text-sm text-muted" for="path-input">File path on server</label>
				<Input
					id="path-input"
					bind:value={pathInput}
					placeholder="/home/user/cinema/Media/clip.mp4"
				/>
			</div>
		{/if}

		<div>
			<label class="mb-1 block text-sm text-muted" for="add-title">Title</label>
			<Input
				id="add-title"
				bind:value={addTitle}
				disabled={batchUpload}
				placeholder={batchUpload ? 'Each file is titled from its own name' : 'Media title'}
			/>
		</div>
		<div>
			<label class="mb-1 block text-sm text-muted" for="add-tags-field">Tags</label>
			<TagInput
				bind:this={addTagInput}
				bind:tags={addTags}
				id="add-tags-field"
				suggestions={tagOptions}
			/>
		</div>
		<div>
			<label class="mb-1 block text-sm text-muted" for="add-audio-format">Audio-format intro</label>
			<Select id="add-audio-format" bind:value={addAudioFormat} class="w-full">
				<option value="">- Not an audio intro -</option>
				{#each AUDIO_FORMATS as [key, label] (key)}
					<option value={key}>{label}</option>
				{/each}
			</Select>
			<p class="mt-1 text-xs text-faint">
				Mark this as a Dolby/DTS intro so an Audio user media block can auto-match it to a feature.
			</p>
		</div>

		{#if addProgress}
			<div>
				<div class="h-1.5 overflow-hidden rounded-xs bg-surface-3">
					<div
						class="h-full bg-accent transition-[width]"
						style="width: {Math.round(addProgress.pct)}%"
					></div>
				</div>
				<p class="mt-1 text-xs text-muted">{addProgress.label}</p>
			</div>
		{/if}
	</div>
	{#snippet footer()}
		<Button onclick={() => (addOpen = false)}>Cancel</Button>
		<Button variant="primary" disabled={uploading || addBusy} onclick={() => void submitAdd()}>
			{#if addMode === 'upload'}<Upload size={14} />
			{:else if addMode === 'youtube'}<Download size={14} />
			{:else}<Plus size={14} />{/if}
			{ADD_MODES.find((m) => m.mode === addMode)?.submit}
		</Button>
	{/snippet}
</Dialog>

<ConfirmDialog bind:this={confirmDialog} />
