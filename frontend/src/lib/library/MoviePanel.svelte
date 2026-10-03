<script lang="ts">
	// The film view in the detail drawer; the library and the dashboard host it.
	import { base } from '$app/paths';
	import {
		AudioLines,
		Check,
		Clapperboard,
		Download,
		ExternalLink,
		Film,
		ListPlus,
		ListVideo,
		ListX,
		Pencil,
		Play,
		Subtitles,
		Trash2,
		X
	} from '@lucide/svelte';
	import { api, unwrap, toApiError } from '$lib/api/client';
	import { unwrapLoose, jobIsActive, type ApiJob } from '$lib/jobs';
	import { mutate } from '$lib/api/mutate';
	import { Query, query } from '$lib/api/query.svelte';
	import type { components } from '$lib/api/types.gen';
	import { formatRuntime, formatSize } from '$lib/format';
	import { showToast } from '$lib/toast.svelte';
	import { attempt } from '$lib/settings/form.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import Dialog from '$lib/components/ui/Dialog.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import SidePanel from '$lib/components/ui/SidePanel.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import Toggle from '$lib/components/ui/Toggle.svelte';

	type MovieDetail = components['schemas']['MovieDetailSchema'];

	/** A click-to-filter request: one facet of the library's filter state. */
	export type MovieFilter =
		| { kind: 'year'; value: number }
		| { kind: 'search'; value: string }
		| { kind: 'genre'; value: string }
		| { kind: 'rating'; value: string };

	interface Props {
		movieId: number;
		/** The host's listed ids, for prev/next. */
		ids?: number[];
		selected?: boolean;
		/** The host's selection, handed to the programme wizard with this film. */
		selectedIds?: number[];
		onclose: () => void;
		onstep?: (id: number) => void;
		/** Given → Select/Deselect is offered. */
		onselect?: () => void;
		/** Given → facet clicks filter the host list in place instead of following the link. */
		onfilter?: (filter: MovieFilter) => void;
		onmutated?: () => void;
		onremoved?: () => void;
		history?: boolean;
		dock?: boolean;
	}

	let {
		movieId,
		ids = [],
		selected = false,
		selectedIds = [],
		onclose,
		onstep,
		onselect,
		onfilter,
		onmutated,
		onremoved,
		history = true,
		dock = true
	}: Props = $props();

	const TRACK_PREVIEW = 5;
	let showAllAudio = $state(false);
	let showAllSubs = $state(false);

	const movie = new Query<MovieDetail>(() =>
		unwrap(api.GET('/api/v2/movies/{movie_id}', { params: { path: { movie_id: movieId } } }))
	);
	$effect(() => {
		void movieId;
		showAllAudio = false;
		showAllSubs = false;
		editingCert = false;
		void movie.load();
	});

	// Supplementary (degrade quietly); the detail payload carries genre ids only.
	const genres = query(() => unwrap(api.GET('/api/v2/movies/genres')));
	const genreNames = $derived.by(() => {
		const list = genres.data ?? [];
		return (movie.data?.genres ?? []).map(
			(id) => list.find((g) => g.id === id)?.name ?? String(id)
		);
	});

	const ratings = query(() => unwrap(api.GET('/api/v2/movies/ratings-options')));
	const certMismatch = $derived(
		!!movie.data?.certification &&
			!!ratings.data &&
			!ratings.data.ratings.includes(movie.data.certification)
	);

	const metaTail = $derived(
		[
			movie.data?.runtime ? formatRuntime(movie.data.runtime) : null,
			movie.data?.date_added
				? `Added ${new Date(movie.data.date_added).toLocaleDateString()}`
				: null
		]
			.filter(Boolean)
			.join(' · ')
	);

	// Escape cancels a certificate edit before it closes the drawer (unless a dialog is on top).
	function onWindowKeydownCapture(e: KeyboardEvent) {
		if (document.querySelector('dialog[open]')) return;
		if (e.key === 'Escape' && editingCert) {
			e.preventDefault();
			e.stopPropagation();
			editingCert = false;
		}
	}

	// Plain clicks filter in place; modifier clicks follow the deep link.
	function filterClick(e: MouseEvent, filter: MovieFilter) {
		if (!onfilter || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
		e.preventDefault();
		onfilter(filter);
	}

	let playTrailerOpen = $state(false);
	const trailerStreamUrl = $derived(
		movie.data?.trailer_id ? `/stream/trailer/${movie.data.trailer_id}/` : null
	);
	$effect(() => {
		void movieId;
		if (!trailerStreamUrl) playTrailerOpen = false;
	});

	// A single-title trailer job, polled home; the outcome lands as a toast.
	let trailerFetching = $state(false);
	async function fetchTrailer() {
		const m = movie.data;
		if (!m?.tmdbid || trailerFetching) return;
		const id = movieId;
		trailerFetching = true;
		try {
			const data = await unwrapLoose<{ job: ApiJob }>(
				api.POST('/api/v2/trailers/fetch', {
					body: {
						type: 'single',
						tmdbid: m.tmdbid,
						replace: false,
						months_ahead: 6,
						limit: 50,
						sort_by: 'popularity.desc'
					}
				})
			);
			let job = data.job;
			while (jobIsActive(job.state)) {
				await new Promise((r) => setTimeout(r, 2000));
				job = (
					await unwrapLoose<{ job: ApiJob }>(
						api.GET('/api/v2/trailers/jobs/{job_id}', { params: { path: { job_id: job.id } } })
					)
				).job;
			}
			if (job.state === 'success') {
				showToast(`Trailer downloaded for ${m.title}`, 'success');
				if (movieId === id) void movie.refresh();
				onmutated?.();
			} else {
				showToast(
					job.error
						? `Trailer fetch failed: ${String(job.error).split('\n')[0]}`
						: `Trailer fetch ${job.state}`,
					'error'
				);
			}
		} catch (e) {
			showToast(toApiError(e).message || 'Could not start the trailer fetch', 'error');
		} finally {
			trailerFetching = false;
		}
	}

	let kioskBusy = $state(false);
	async function toggleKiosk() {
		if (kioskBusy || !movie.data) return;
		kioskBusy = true;
		await attempt(async () => {
			const msg = await mutate(
				api.POST('/api/v2/movies/{movie_id}/toggle_kiosk', {
					params: { path: { movie_id: movieId } }
				})
			);
			movie.data!.kiosk_display = !movie.data!.kiosk_display;
			showToast(msg ?? 'Kiosk display updated', 'success');
			onmutated?.();
		}, 'Failed to toggle kiosk status');
		kioskBusy = false;
	}

	let editingCert = $state(false);
	let certValue = $state('');
	let certSaving = $state(false);

	function startCertEdit() {
		if (!ratings.data) {
			showToast('Could not load rating options', 'error');
			void ratings.refresh();
			return;
		}
		const current = movie.data?.certification ?? '';
		certValue = ratings.data.ratings.includes(current) ? current : '';
		editingCert = true;
	}

	async function saveCert() {
		if (certSaving) return;
		certSaving = true;
		await attempt(async () => {
			const result = await unwrap(
				api.PATCH('/api/v2/movies/{movie_id}/certification', {
					params: { path: { movie_id: movieId } },
					body: { certification: certValue || null }
				})
			);
			if (movie.data) {
				movie.data.certification = result.certification;
				movie.data.certificates = result.certificates;
			}
			editingCert = false;
			showToast(
				result.certification ? `Rating set to ${result.certification}` : 'Rating cleared',
				'success'
			);
			onmutated?.();
		}, 'Failed to update rating');
		certSaving = false;
	}

	let confirmDialog: ConfirmDialog;
	let deleting = $state(false);
	async function removeMovie() {
		if (deleting || !movie.data) return;
		const ok = await confirmDialog.confirm(
			`Remove "${movie.data.title}" from the Cinefin library? The file on disk is not deleted.`,
			{ confirmLabel: 'Remove' }
		);
		if (!ok) return;
		deleting = true;
		const title = movie.data.title;
		await attempt(async () => {
			await mutate(
				api.DELETE('/api/v2/movies/{movie_id}', { params: { path: { movie_id: movieId } } })
			);
			showToast(`"${title}" removed from the library`, 'success');
			onremoved?.();
		}, 'Failed to remove movie');
		deleting = false;
	}

	const createHref = $derived.by(() => {
		const list = selectedIds.includes(movieId) ? selectedIds : [...selectedIds, movieId];
		return `${base}/programmes/create?movies=${list.join(',')}`;
	});

	function formatBitrate(bps: number): string {
		if (bps >= 1e6) return `${(bps / 1e6).toFixed(1)} Mbps`;
		if (bps >= 1000) return `${Math.round(bps / 1000)} Kbps`;
		return `${bps} bps`;
	}

	// Text badges, not logos: the Dolby/DTS marks are trademarks.
	function audioBrand(codec: string): string | null {
		const c = codec.toLowerCase();
		if (/truehd|ac3|eac3/.test(c)) return 'Dolby';
		if (/dts|dca/.test(c)) return 'DTS';
		return null;
	}
</script>

<svelte:window onkeydowncapture={onWindowKeydownCapture} />

{#snippet trackIndex(index: number | null | undefined)}
	<span class="font-mono text-xs whitespace-nowrap text-faint">Track {index ?? 'N/A'}</span>
{/snippet}

{#snippet more(all: boolean, label: string, toggle: () => void)}
	<button type="button" class="mt-1.5 text-xs text-accent hover:underline" onclick={toggle}>
		{all ? 'Show fewer' : label}
	</button>
{/snippet}

<SidePanel
	label={movie.data?.title ?? 'Film'}
	{ids}
	currentId={movieId}
	{onstep}
	{onclose}
	{history}
	{dock}
>
	{#if movie.loading}
		<Spinner label="Loading movie…" />
	{:else if movie.error}
		<ErrorState error={movie.error} retry={() => void movie.load()} compact />
	{:else if movie.data}
		{@const m = movie.data}
		{@const v = m.video_info}

		<div class="flex flex-col gap-4 @xs:flex-row @sm:gap-5">
			<div
				class="film-grain aspect-[2/3] w-28 shrink-0 overflow-hidden border border-border
						bg-surface-2 @sm:w-36 @lg:w-40"
			>
				{#if m.thumbnail_url}
					<img src={m.thumbnail_url} alt={m.title} class="h-full w-full object-cover" />
				{:else}
					<div class="flex h-full items-center justify-center text-faint">
						<Film size={32} />
					</div>
				{/if}
			</div>

			<div class="min-w-0 flex-1 space-y-3">
				<h2 class="text-xl leading-tight font-semibold">{m.title}</h2>

				<p class="text-sm text-muted">
					{#if m.year}
						<a
							href="{base}/library?year={m.year}"
							class="hover:text-accent"
							title="Show movies from {m.year}"
							onclick={(e) => filterClick(e, { kind: 'year', value: m.year! })}>{m.year}</a
						>
					{/if}
					{#if m.director}
						{m.year ? ' · ' : ''}<a
							href="{base}/library?search={encodeURIComponent(m.director)}"
							class="hover:text-accent"
							title="Show movies by {m.director}"
							onclick={(e) => filterClick(e, { kind: 'search', value: m.director! })}
							>{m.director}</a
						>
					{/if}{#if metaTail}{m.year || m.director ? ' · ' : ''}{metaTail}{/if}
				</p>

				<div class="flex flex-wrap items-center gap-1.5">
					{#if editingCert}
						<span class="inline-flex items-center gap-1">
							<Select bind:value={certValue} class="h-7 text-xs">
								<option value="">Unrated</option>
								{#each ratings.data?.ratings ?? [] as r (r)}
									<option value={r}>{r}</option>
								{/each}
							</Select>
							<Button
								size="sm"
								variant="ghost"
								title="Save rating"
								disabled={certSaving}
								onclick={saveCert}
							>
								<Check size={14} />
							</Button>
							<Button
								size="sm"
								variant="ghost"
								title="Cancel"
								onclick={() => (editingCert = false)}
							>
								<X size={14} />
							</Button>
						</span>
					{:else}
						<span class="inline-flex items-center gap-0.5">
							{#if m.certification}
								<a
									href="{base}/library?rating={encodeURIComponent(m.certification)}"
									title="Show all {m.certification} movies"
									class="hover:opacity-80"
									onclick={(e) => filterClick(e, { kind: 'rating', value: m.certification! })}
								>
									<Badge variant={certMismatch ? 'warning' : 'outline'}>
										{m.certification}
									</Badge>
								</a>
							{:else}
								<Badge variant="default">Unrated</Badge>
							{/if}
							<Button size="sm" variant="ghost" title="Edit rating" onclick={startCertEdit}>
								<Pencil size={12} />
							</Button>
						</span>
					{/if}
					{#if m.tmdbid === 0}<Badge variant="outline">No TMDB</Badge>{/if}
					{#if selected}<Badge variant="accent">Selected</Badge>{/if}
				</div>
				{#if certMismatch && ratings.data}
					<p class="text-xs text-warning">
						Rating “{m.certification}” is not a {ratings.data.system} rating.
					</p>
				{/if}

				{#if genreNames.length}
					<div class="flex flex-wrap gap-1.5">
						{#each genreNames as g (g)}
							<a
								href="{base}/library?genre={encodeURIComponent(g)}"
								title="Show {g} movies"
								class="hover:opacity-80"
								onclick={(e) => filterClick(e, { kind: 'genre', value: g })}
							>
								<Badge variant="default">{g}</Badge>
							</a>
						{/each}
					</div>
				{/if}

				<p class="text-sm leading-relaxed">{m.description || 'No synopsis available.'}</p>

				<div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
					{#if m.has_trailer}
						{@const trailerHref = m.trailer_id
							? `${base}/trailers?trailer=${m.trailer_id}`
							: `${base}/trailers?q=${encodeURIComponent(m.title)}`}
						<a
							href={trailerHref}
							class="inline-flex items-center gap-1.5 hover:text-accent"
							title="Open this film's entry in the trailer library"
						>
							<Clapperboard size={12} /> Trailer in library
						</a>
					{:else}
						<span class="inline-flex items-center gap-1.5">
							<Clapperboard size={12} /> No trailer downloaded
						</span>
					{/if}
					{#if trailerStreamUrl}
						<button
							type="button"
							class="inline-flex items-center gap-1.5 text-accent hover:underline"
							title="Play this movie's trailer from your library"
							onclick={() => (playTrailerOpen = true)}
						>
							<Play size={12} /> Play trailer
						</button>
					{:else if m.tmdbid && !m.has_trailer}
						<button
							type="button"
							class="inline-flex items-center gap-1.5 text-accent hover:underline disabled:opacity-50"
							disabled={trailerFetching}
							title="Download this movie's trailer (TMDB → YouTube)"
							onclick={() => void fetchTrailer()}
						>
							<Download size={12} />
							{trailerFetching ? 'Fetching trailer…' : 'Fetch trailer'}
						</button>
					{/if}
					{#if m.tmdbid}
						<a
							href="https://www.themoviedb.org/movie/{m.tmdbid}"
							target="_blank"
							rel="noopener"
							class="inline-flex items-center gap-1.5 hover:text-accent"
						>
							TMDB #{m.tmdbid}
							<ExternalLink size={11} />
						</a>
					{/if}
				</div>

				<Toggle
					label="Show on the kiosk display"
					checked={m.kiosk_display}
					disabled={kioskBusy}
					onchange={(e) => {
						const box = e.currentTarget as HTMLInputElement;
						void toggleKiosk().then(() => (box.checked = !!movie.data?.kiosk_display));
					}}
				/>
			</div>
		</div>

		<div class="mt-5 grid gap-x-8 gap-y-5 border-t border-border pt-4 @3xl:grid-cols-2">
			{#snippet fact(label: string, value: string | false | undefined)}
				{#if value}
					<div class="flex justify-between gap-4">
						<dt class="text-muted">{label}</dt>
						<dd class="font-mono">{value}</dd>
					</div>
				{/if}
			{/snippet}
			<section>
				<h3 class="mb-2 text-sm font-semibold">File</h3>
				<dl class="space-y-1.5 text-sm">
					{#if m.file_path}
						<div class="flex justify-between gap-4">
							<dt class="shrink-0 text-muted">Path</dt>
							<dd class="min-w-0 text-right font-mono text-xs leading-5 break-all">
								{m.file_path}
							</dd>
						</div>
					{/if}
					{@render fact('Size', formatSize(m.file_size) || '-')}
					{@render fact(
						'Resolution',
						v?.width && v?.height ? `${v.width} × ${v.height}` : m.resolution || '-'
					)}
					{@render fact('Codec', v?.codec?.toUpperCase())}
					{@render fact('Frame rate', !!v?.framerate && `${Number(v.framerate.toFixed(3))} fps`)}
					{@render fact('Bitrate', !!v?.bitrate && formatBitrate(v.bitrate))}
				</dl>
			</section>

			<section>
				<h3 class="mb-2 text-sm font-semibold">Certificates</h3>
				{#if Object.keys(m.certificates ?? {}).length}
					<dl class="space-y-1.5 text-sm">
						{#each Object.entries(m.certificates) as [system, cert] (system)}
							<div class="flex justify-between gap-4">
								<dt class="text-muted">{system}</dt>
								<dd>
									<Badge variant={system === ratings.data?.system ? 'accent' : 'outline'}>
										{cert}
									</Badge>
								</dd>
							</div>
						{/each}
					</dl>
				{:else}
					<p class="text-sm text-muted">No certificates recorded for any ratings system.</p>
				{/if}
			</section>

			<section>
				<h3 class="mb-2 text-sm font-semibold">Audio tracks ({m.audio_tracks.length})</h3>
				{#if m.audio_tracks.length}
					<ul class="divide-y divide-border">
						{#each showAllAudio ? m.audio_tracks : m.audio_tracks.slice(0, TRACK_PREVIEW) as track (track.id)}
							{@const brand = audioBrand(track.codec)}
							<!-- Grid: only the (long) track title truncates. -->
							<li
								class="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-2 py-1.5 text-sm"
							>
								<AudioLines size={14} class="text-faint" />
								<span class="flex min-w-0 items-center gap-1.5">
									<span class="shrink-0">{track.language || 'Unknown'}</span>
									{#if brand}<Badge variant="accent">{brand}</Badge>{/if}
									{#if track.codec}<Badge variant="outline">{track.codec.toUpperCase()}</Badge>{/if}
									{#if track.channels}<Badge variant="outline">{track.channels} CH</Badge>{/if}
									{#if track.title}
										<span class="min-w-0 truncate text-xs text-muted" title={track.title}>
											{track.title}
										</span>
									{/if}
								</span>
								{@render trackIndex(track.index)}
							</li>
						{/each}
					</ul>
					{#if m.audio_tracks.length > TRACK_PREVIEW}
						{@render more(
							showAllAudio,
							`Show all ${m.audio_tracks.length} audio tracks`,
							() => (showAllAudio = !showAllAudio)
						)}
					{/if}
				{:else}
					<p class="text-sm text-muted">No audio track information available.</p>
				{/if}
			</section>

			<section>
				<h3 class="mb-2 text-sm font-semibold">Subtitles ({m.subtitle_tracks.length})</h3>
				{#if m.subtitle_tracks.length}
					<ul class="divide-y divide-border">
						{#each showAllSubs ? m.subtitle_tracks : m.subtitle_tracks.slice(0, TRACK_PREVIEW) as track (track.id)}
							<li
								class="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-2 py-1.5 text-sm"
							>
								<Subtitles size={14} class="text-faint" />
								<span class="flex min-w-0 items-center gap-1.5">
									<span class="truncate">{track.language || 'Unknown'}</span>
									{#if track.forced}<Badge variant="outline">Forced</Badge>{/if}
									{#if track.sdh}<Badge variant="outline">SDH</Badge>{/if}
								</span>
								{@render trackIndex(track.index)}
							</li>
						{/each}
					</ul>
					{#if m.subtitle_tracks.length > TRACK_PREVIEW}
						{@render more(
							showAllSubs,
							`Show all ${m.subtitle_tracks.length} subtitles`,
							() => (showAllSubs = !showAllSubs)
						)}
					{/if}
				{:else}
					<p class="text-sm text-muted">No subtitle track information available.</p>
				{/if}
			</section>
		</div>

		<!-- Rare and destructive: at the end, not beside the everyday actions. -->
		<div class="mt-6 border-t border-border pt-4">
			<button
				type="button"
				class="inline-flex items-center gap-1.5 text-sm text-danger hover:underline disabled:opacity-50"
				disabled={deleting}
				onclick={() => void removeMovie()}
			>
				<Trash2 size={14} /> Remove from library
			</button>
			<p class="mt-1 text-xs text-faint">
				Takes the film out of Cinefin. The file on disk is kept.
			</p>
		</div>
	{/if}

	{#snippet footer()}
		<div class="grid w-full gap-2 {onselect ? 'grid-cols-2' : 'grid-cols-1'}">
			{#if onselect}
				<Button
					class="w-full justify-center"
					onclick={onselect}
					title={selected
						? 'Take this movie out of the programme selection'
						: 'Add this movie to the programme selection'}
				>
					{#if selected}<ListX size={14} /> Deselect{:else}<ListPlus size={14} /> Select{/if}
				</Button>
			{/if}
			<Button
				class="w-full justify-center"
				variant="primary"
				href={createHref}
				title={selectedIds.length && !selectedIds.includes(movieId)
					? `Create a programme from the ${selectedIds.length} selected movie${selectedIds.length === 1 ? '' : 's'} plus this one`
					: selectedIds.length > 1
						? `Create a programme from the ${selectedIds.length} selected movies`
						: 'Create a programme with this movie'}
			>
				<ListVideo size={14} /> Create programme
			</Button>
		</div>
	{/snippet}
</SidePanel>

<!-- The <video> mounts only while open, so closing releases the stream. -->
<Dialog
	bind:open={playTrailerOpen}
	title={movie.data ? `${movie.data.title} - trailer` : 'Trailer'}
	size="3xl"
>
	{#if playTrailerOpen && trailerStreamUrl}
		<!-- svelte-ignore a11y_media_has_caption -->
		<video controls autoplay src={trailerStreamUrl} class="max-h-[70vh] w-full bg-black"></video>
	{/if}
</Dialog>

<ConfirmDialog bind:this={confirmDialog} title="Remove from library" />
