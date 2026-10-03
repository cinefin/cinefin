<script lang="ts">
	import PageHeader from '$lib/components/shell/PageHeader.svelte';
	import { base } from '$app/paths';
	import {
		ChevronLeft,
		ChevronRight,
		CloudUpload,
		Download,
		FilterX,
		Film,
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
	import { mutate } from '$lib/api/mutate';
	import { Query } from '$lib/api/query.svelte';
	import { uploadWithProgress } from '$lib/upload';
	import { showToast as toast } from '$lib/toast.svelte';
	import { actMsg } from '$lib/media/actions';
	import { Selection } from '$lib/selection.svelte';
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

	const audioFormatLabel = (key: string | null | undefined) =>
		AUDIO_FORMATS.find(([k]) => k === key)?.[1] ?? '';

	function fmtDuration(seconds: number | null | undefined): string {
		const s = Math.round(Number(seconds) || 0);
		return s ? formatTime(s) : '';
	}

	function fmtSize(bytes: number | null | undefined): string {
		const b = Number(bytes) || 0;
		if (b === 0) return '';
		const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
		const i = Math.min(sizes.length - 1, Math.floor(Math.log(b) / Math.log(1024)));
		return `${parseFloat((b / Math.pow(1024, i)).toFixed(2))} ${sizes[i]}`;
	}

	function fmtDate(iso: string | null | undefined): string {
		const d = new Date(iso ?? '');
		return !iso || isNaN(d.getTime())
			? '-'
			: d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
	}

	const fileExists = (m: MediaItem) => m.file_info.exists !== false;
	const isAudio = (m: MediaItem) => (m.file_info.mime_type ?? '').startsWith('audio');
	const subLine = (m: MediaItem) =>
		[fmtDuration(m.duration), fmtSize(m.file_info.size), audioFormatLabel(m.audio_format)]
			.filter(Boolean)
			.join(' · ');
	const fileTitle = (f: File) => f.name.replace(/\.[^.]+$/, '');

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

	/** Set a filter (or the sort) and go back to the first page. */
	function refilter(set: () => void) {
		set();
		page = 1;
	}

	const headerSort = (next: string) => refilter(() => (sort = next));

	function onDrag(e: DragEvent) {
		e.preventDefault();
		dragOver = e.type === 'dragover' || e.type === 'dragenter';
		if (e.type === 'drop') pickFiles(e.dataTransfer?.files);
	}

	$effect(() => media.live());

	const items = $derived(media.data?.media ?? []);
	const pg = $derived(media.data?.pagination);
	const tagOptions = $derived(media.data?.filters.tags ?? []);
	const filtersActive = $derived(Boolean(search) || tags.length > 0);

	const tagFacets = $derived(media.data?.filters.tag_facets ?? []);

	function clearFilters() {
		search = '';
		tags = [];
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

	const picked = new Selection(() => items);

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
	let edit = $state({ item: null as MediaItem | null, title: '', tags: [] as string[], audio: '' });
	let editBusy = $state(false);
	// The edit and add forms' tag inputs, to commit what is typed before a save.
	const tagInputs = $state<Record<string, TagInput | undefined>>({});

	function openEdit(m: MediaItem) {
		edit = {
			item: m,
			title: m.title,
			tags: m.tags.map((t) => t.name),
			audio: m.audio_format ?? ''
		};
		editing = true;
	}

	// Escape backs out of the form before it closes the drawer.
	function onEditKeydown(e: KeyboardEvent) {
		if (e.key !== 'Escape' || !editing || document.querySelector('dialog[open]')) return;
		e.preventDefault();
		editing = false;
	}

	async function saveEdit() {
		const item = edit.item;
		if (!item) return;
		tagInputs.edit?.commit();
		editBusy = true;
		await actMsg('Failed to update media', async () => {
			await unwrap(
				api.PUT('/api/v2/media/{media_id}', {
					params: { path: { media_id: item.id } },
					body: { title: edit.title.trim(), tag_names: edit.tags, audio_format: edit.audio }
				})
			);
			toast('Media updated', 'success');
			editing = false;
			await media.refresh();
		});
		editBusy = false;
	}

	async function remove(id: number, title: string) {
		const msg = `Delete “${title}” from the library? (The file on disk is left untouched.)`;
		if (!(await confirmDialog!.confirm(msg, { confirmLabel: 'Delete' }))) return;
		await actMsg('Failed to delete media', async () => {
			await api.DELETE('/api/v2/media/{media_id}', { params: { path: { media_id: id } } });
			toast('Media removed', 'success');
			if (selectedId === id) closeDetail();
			await media.refresh();
		});
	}

	let rethumbBusy = $state(false);
	let rethumbItemBusy = $state<number | null>(null);

	async function regenerateThumbnails(mediaId: number | null) {
		const ask = 'Regenerate thumbnails for every video in the media library?';
		if (mediaId === null && !(await confirmDialog!.confirm(ask, { confirmLabel: 'Regenerate' })))
			return;
		if (mediaId === null) rethumbBusy = true;
		else rethumbItemBusy = mediaId;
		await actMsg('Could not regenerate thumbnails', async () => {
			const query = mediaId === null ? {} : { media_id: mediaId };
			const msg = await mutate(
				api.POST('/api/v2/media/thumbnails/regenerate', { params: { query } })
			);
			toast(msg || 'Thumbnails regenerated', 'success');
			if (mediaId === null) thumbVersion = Date.now();
			else thumbBustById = { ...thumbBustById, [mediaId]: Date.now() };
			void media.refresh();
		});
		rethumbBusy = false;
		rethumbItemBusy = null;
	}

	interface UploadEntry {
		file: File;
		status: 'pending' | 'uploading' | 'done' | 'error';
		pct: number;
		error: string | null;
	}

	type AddMode = 'upload' | 'youtube' | 'path';
	const ADD_MODES = [
		{ mode: 'upload', label: 'Upload file', submit: 'Upload', icon: Upload },
		{ mode: 'youtube', label: 'YouTube', submit: 'Download', icon: Download },
		{ mode: 'path', label: 'Server path', submit: 'Add', icon: Plus }
	] as const;

	const blankAdd = () => ({
		mode: 'upload' as AddMode,
		uploads: [] as UploadEntry[],
		uploading: false,
		busy: false,
		title: '',
		tags: [] as string[],
		audio: '',
		ytUrl: '',
		path: '',
		progress: null as { pct: number; label: string } | null
	});
	let add = $state(blankAdd());
	let addOpen = $state(false);
	let dragOver = $state(false);
	let fileInput = $state<HTMLInputElement>();

	function openAdd() {
		add = blankAdd();
		addOpen = true;
	}

	function setAddMode(mode: AddMode) {
		add.mode = mode;
		add.progress = null;
		syncTitleField();
	}

	// A batch always titles each file from its own name; a single file uses the title field.
	const batchUpload = $derived(add.mode === 'upload' && add.uploads.length > 1);
	function syncTitleField() {
		if (batchUpload) add.title = '';
		else if (add.mode === 'upload' && add.uploads.length === 1 && !add.title.trim()) {
			add.title = fileTitle(add.uploads[0].file);
		}
	}

	function pickFiles(fileList: FileList | null | undefined) {
		const files = [...(fileList ?? [])];
		if (!files.length || add.uploading) return;
		for (const file of files) {
			const dup = add.uploads.some((u) => u.file.name === file.name && u.file.size === file.size);
			if (!dup) add.uploads.push({ file, status: 'pending', pct: 0, error: null });
		}
		syncTitleField();
	}

	function removeUpload(i: number) {
		if (add.uploading) return;
		add.uploads.splice(i, 1);
		syncTitleField();
	}

	async function applyAudioFormat(mediaId: number | null | undefined) {
		if (!mediaId || !add.audio) return;
		try {
			await unwrap(
				api.PUT('/api/v2/media/{media_id}', {
					params: { path: { media_id: mediaId } },
					body: { audio_format: add.audio }
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
		tagInputs.add?.commit();
		const title = add.title.trim();
		if (add.mode === 'upload') return submitUploadBatch();
		if (add.mode === 'youtube') {
			const url = add.ytUrl.trim();
			if (!url) return toast('Enter a YouTube URL', 'error');
			add.busy = true;
			add.progress = { pct: 0, label: 'Starting…' };
			const data = await actMsg('Failed to add media', () =>
				unwrap(
					api.POST('/api/v2/media/youtube-download', {
						body: { url, title: title || null, tag_names: add.tags }
					})
				)
			);
			if (data) return monitorYoutube(data.task_id);
			add.busy = false;
			add.progress = null;
			return;
		}
		const path = add.path.trim();
		if (!path) return toast('Enter a file path', 'error');
		if (!title) return toast('Enter a title', 'error');
		add.busy = true;
		await actMsg('Failed to add media', async () => {
			const created = await unwrap(
				api.POST('/api/v2/media/create', { body: { file_path: path, title, tag_names: add.tags } })
			);
			await applyAudioFormat((created as MediaCreated).id);
			finishAdd('Media added');
		});
		add.busy = false;
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
			add.progress = { pct, label: `Downloading ${Math.round(pct)}%` };
		}
		add.busy = false;
		add.progress = null;
	}

	// Failed files stay queued for a retry; the modal only closes when everything succeeded.
	async function submitUploadBatch() {
		const todo = add.uploads.filter((u) => u.status !== 'done');
		if (!todo.length) return toast('Choose a video or audio file first', 'error');
		add.uploading = true;

		let ok = 0;
		for (const u of todo) {
			Object.assign(u, { status: 'uploading', pct: 0, error: null });
			try {
				const title =
					add.uploads.length === 1 && add.title.trim() ? add.title.trim() : fileTitle(u.file);
				const created = await uploadWithProgress<MediaCreated>(
					'/api/v2/media/upload',
					u.file,
					{ title, tag_names: add.tags.join(',') },
					(e) => (u.pct = e.percent)
				);
				Object.assign(u, { status: 'done', pct: 100 });
				await applyAudioFormat(created.id);
				ok++;
			} catch (e) {
				console.error(`Upload failed for ${u.file.name}:`, e);
				Object.assign(u, { status: 'error', error: toApiError(e).message || 'Upload failed' });
			}
		}
		const failed = todo.length - ok;

		add.uploading = false;
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

	const UPLOAD_STATE = { pending: 'Queued', done: 'Done', error: 'Failed' };
	const UPLOAD_COLOUR = {
		pending: 'text-muted',
		uploading: 'text-muted',
		done: 'text-success',
		error: 'text-danger'
	};
	function uploadStateLabel(u: UploadEntry): string {
		if (u.status !== 'uploading') return UPLOAD_STATE[u.status];
		return u.pct >= 100 ? 'Processing…' : `${Math.round(u.pct)}%`;
	}
</script>

<svelte:window onkeydowncapture={onEditKeydown} />

{#snippet kindIcon(m: MediaItem, size: number)}
	{#if !fileExists(m)}<TriangleAlert {size} class="text-warning" />
	{:else if isAudio(m)}<Music {size} />
	{:else}<Film {size} />{/if}
{/snippet}

{#snippet pickBox(m: MediaItem, label?: string)}
	<input
		type="checkbox"
		class="accent-accent"
		aria-label={label}
		checked={picked.has(m.id)}
		onclick={(e) => picked.toggle(m.id, e.currentTarget.checked, e.shiftKey)}
	/>
{/snippet}

{#snippet metaFields(
	form: 'edit' | 'add',
	f: { title: string; tags: string[]; audio: string },
	hint: string
)}
	<div>
		<label class="mb-1 block text-sm text-muted" for="{form}-title">Title</label>
		<Input
			id="{form}-title"
			bind:value={f.title}
			disabled={form === 'add' && batchUpload}
			placeholder={form === 'edit'
				? undefined
				: batchUpload
					? 'Each file is titled from its own name'
					: 'Media title'}
		/>
	</div>
	<div>
		<label class="mb-1 block text-sm text-muted" for="{form}-tags-field">Tags</label>
		<TagInput
			bind:this={tagInputs[form]}
			bind:tags={f.tags}
			id="{form}-tags-field"
			suggestions={tagOptions}
		/>
	</div>
	<div>
		<label class="mb-1 block text-sm text-muted" for="{form}-audio-format">Audio-format intro</label
		>
		<Select id="{form}-audio-format" bind:value={f.audio} class="w-full">
			<option value="">- Not an audio intro -</option>
			{#each AUDIO_FORMATS as [key, label] (key)}<option value={key}>{label}</option>{/each}
		</Select>
		<p class="mt-1 text-xs text-faint">{hint}</p>
	</div>
{/snippet}

{#snippet fact(label: string, value: string, mono = false)}
	{#if value}
		<div class="flex justify-between gap-4">
			<dt class="text-muted">{label}</dt>
			<dd class={mono ? 'font-mono' : undefined}>{value}</dd>
		</div>
	{/if}
{/snippet}

{#snippet tagList(m: MediaItem, gap: string)}
	<div class="flex flex-wrap {gap}">
		{#each m.tags as t (t.id)}<TagBadge color={t.color}>{t.name}</TagBadge>{/each}
	</div>
{/snippet}

{#snippet thumb(m: MediaItem, img: string, box: string, size: number)}
	{#if fileExists(m) && m.screenshot_url}
		<img
			src={bust(m.screenshot_url, m.id)}
			alt=""
			loading="lazy"
			onerror={hideBrokenImg}
			class={img}
		/>
	{:else}
		<span class="flex items-center justify-center text-faint {box}"
			>{@render kindIcon(m, size)}</span
		>
	{/if}
{/snippet}

<PageHeader title="User media" {actions} />
{#snippet actions()}
	<Button
		onclick={() => void regenerateThumbnails(null)}
		disabled={rethumbBusy}
		title="Re-extract the screenshot thumbnails from every video"
	>
		<RotateCw size={14} /> Regenerate thumbnails
	</Button>
	<Button variant="primary" onclick={openAdd}><Plus size={14} /> Add media</Button>
{/snippet}

<p class="mb-4 text-sm text-muted">
	Theater idents, audio-format intros and the other clips used as programme building blocks. Movies
	live in the <a href="{base}/library" class="text-accent hover:underline">Library</a>, trailers in
	the <a href="{base}/trailers" class="text-accent hover:underline">Trailer library</a>.
</p>

<FilterBar
	search={{
		value: search,
		placeholder: 'Search by title…',
		onchange: (v) => refilter(() => (search = v))
	}}
	count={countText}
	bind:view
	viewKey="media_view"
	onreset={clearFilters}
/>

<MediaTagBar
	tags={tagFacets}
	filter={tags}
	onfilter={(names) => refilter(() => (tags = names))}
	picked={items.filter((m) => picked.has(m.id))}
	onchanged={() => media.refresh()}
	onclearpick={() => picked.clear()}
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
						{@render pickBox(m)}
					</label>
					<button
						type="button"
						class="block h-full w-full cursor-pointer"
						onclick={() => openDetail(m.id)}
						title={m.title || 'Untitled'}
					>
						{@render thumb(
							m,
							'h-full w-full object-cover transition-opacity group-hover:opacity-80',
							'h-full w-full',
							22
						)}
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
							checked={picked.allVisible}
							onchange={(e) => picked.setVisible((e.currentTarget as HTMLInputElement).checked)}
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
							{@render pickBox(m, `Select ${m.title || 'item'}`)}
						</td>
						<td class="px-3 py-1.5">
							{@render thumb(
								m,
								'h-9 w-16 rounded-sm border border-border object-cover',
								'h-9 w-16 rounded-sm border border-border bg-surface-2',
								14
							)}
						</td>
						<td class="px-3 py-1.5" title={m.file_path}>
							{m.title || 'Untitled'}
							{#if !exists}<StatusLamp colour="amber" class="ml-1.5">File missing</StatusLamp>{/if}
						</td>
						<td class="px-3 py-1.5">
							{#if m.tags.length}
								{@render tagList(m, 'gap-1')}
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
				<div class="mt-4 space-y-4">
					{@render metaFields(
						'edit',
						edit,
						'Mark this clip as the intro for an audio format so it can auto-play before matching features.'
					)}
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

				{#if m.tags.length}{@render tagList(m, 'mt-4 gap-1.5')}{/if}

				<dl class="mt-4 space-y-1.5 text-sm">
					{@render fact('Type', isAudio(m) ? 'Audio' : 'Video')}
					{@render fact('Duration', fmtDuration(m.duration), true)}
					{@render fact('Size', fmtSize(m.file_info.size), true)}
					{@render fact('Audio-format intro', audioFormatLabel(m.audio_format))}
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
				<Button onclick={() => void remove(m.id, m.title)}><Trash2 size={14} /> Delete</Button>
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
			value={add.mode}
			label="How to add media"
			onselect={(id) => setAddMode(id as AddMode)}
		/>

		{#if add.mode === 'upload'}
			<button
				type="button"
				class="flex w-full flex-col items-center gap-1.5 rounded-md border-2 border-dashed px-4 py-6 text-center
					{dragOver
					? 'border-accent bg-accent/5'
					: 'border-border-strong bg-surface-2 hover:border-accent-dim'}"
				onclick={() => fileInput?.click()}
				ondragover={onDrag}
				ondragenter={onDrag}
				ondragleave={onDrag}
				ondrop={onDrag}
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

			{#if add.uploads.length}
				<div class="space-y-2">
					{#each add.uploads as u, i (u.file.name + u.file.size)}
						<div class="rounded-md border border-border bg-surface-2 p-2">
							<div class="flex items-center gap-2 text-xs">
								<span class="min-w-0 flex-1 truncate" title={u.file.name}>{u.file.name}</span>
								<span class="shrink-0 font-mono text-faint">{fmtSize(u.file.size)}</span>
								<span class="shrink-0 font-mono {UPLOAD_COLOUR[u.status]}">
									{uploadStateLabel(u)}
								</span>
								{#if (u.status === 'pending' || u.status === 'error') && !add.uploading}
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
							{#if u.error}<p class="mt-1 text-xs text-danger">{u.error}</p>{/if}
						</div>
					{/each}
				</div>
			{/if}
		{:else if add.mode === 'youtube'}
			<div>
				<label class="mb-1 block text-sm text-muted" for="yt-url">YouTube URL</label>
				<Input id="yt-url" bind:value={add.ytUrl} placeholder="https://www.youtube.com/watch?v=…" />
			</div>
		{:else}
			<div>
				<label class="mb-1 block text-sm text-muted" for="path-input">File path on server</label>
				<Input
					id="path-input"
					bind:value={add.path}
					placeholder="/home/user/cinema/Media/clip.mp4"
				/>
			</div>
		{/if}

		{@render metaFields(
			'add',
			add,
			'Mark this as a Dolby/DTS intro so an Audio user media block can auto-match it to a feature.'
		)}

		{#if add.progress}
			<div>
				<div class="h-1.5 overflow-hidden rounded-xs bg-surface-3">
					<div
						class="h-full bg-accent transition-[width]"
						style="width: {Math.round(add.progress.pct)}%"
					></div>
				</div>
				<p class="mt-1 text-xs text-muted">{add.progress.label}</p>
			</div>
		{/if}
	</div>
	{#snippet footer()}
		<Button onclick={() => (addOpen = false)}>Cancel</Button>
		{@const m = ADD_MODES.find((m) => m.mode === add.mode)!}
		<Button variant="primary" disabled={add.uploading || add.busy} onclick={() => void submitAdd()}>
			<m.icon size={14} />
			{m.submit}
		</Button>
	{/snippet}
</Dialog>

<ConfirmDialog bind:this={confirmDialog} />
