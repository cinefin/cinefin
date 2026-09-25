<script lang="ts">
	// Editing happens here (issue #404): `?edit=1` swaps the Rundown tab for the
	// ProgrammeEditor. `/programmes/new` is this route with a virtual id — nothing
	// is written until the first save, so an abandoned start leaves nothing behind.
	import { page } from '$app/state';
	import { base } from '$app/paths';
	import { goto } from '$app/navigation';
	import {
		ArrowLeft,
		CalendarPlus,
		Check,
		PanelLeftOpen,
		Pencil,
		RefreshCw,
		Trash2,
		Upload
	} from '@lucide/svelte';
	import { api, toApiError, unwrap } from '$lib/api/client';
	import { Query, query } from '$lib/api/query.svelte';
	import type { components } from '$lib/api/types.gen';
	import type {
		ProgrammeItem,
		ProgrammePlaylist,
		ProgrammePlaylistItem
	} from '$lib/programmes/types';
	import { formatLongRuntime } from '$lib/programmes/helpers';
	import { formatClock } from '$lib/format';
	import Banner from '$lib/components/ui/Banner.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import TitleConfigCard from '$lib/programmes/TitleConfigCard.svelte';
	import AsideToggle from '$lib/components/AsideToggle.svelte';
	import FeaturePanel from '$lib/programmes/detail-FeaturePanel.svelte';
	import ProgrammeEditor from '$lib/programmes/ProgrammeEditor.svelte';
	import { takeStashedFilms } from '$lib/programmes/blank-handoff';
	import Rundown from '$lib/programmes/detail-Rundown.svelte';
	import Tabs from '$lib/components/ui/Tabs.svelte';
	import TicketsPanel from '$lib/programmes/detail-TicketsPanel.svelte';
	import TracksDialog from '$lib/programmes/detail-TracksDialog.svelte';
	import { showToast } from '$lib/toast.svelte';
	import { invalidate } from '$lib/invalidate';

	type ProgrammeDetail = components['schemas']['ProgrammeDetailSchema'];
	type DesignSummary = components['schemas']['DesignSummarySchema'];
	type MovieDetail = components['schemas']['MovieDetailSchema'];

	const isNew = $derived(page.params.id === 'new');
	// Read once from the route param, not the derived: the stash is single-use,
	// so a reload starts from an empty running order instead of re-adding films.
	const handedOverFilms = page.params.id === 'new' ? takeStashedFilms() : [];
	// NaN while `new` — every use is behind `isNew`, and no query runs.
	const programmeId = $derived(Number(page.params.id));

	const prog = new Query<{ programme: ProgrammeDetail }>(() =>
		unwrap(
			api.GET('/api/v2/programmes/{programme_id}', {
				params: { path: { programme_id: programmeId } }
			})
		)
	);

	// Cast through unknown — the generated type for this endpoint is wrong
	// (schema-name collision, see $lib/programmes/types.ts).
	const playlist = new Query<ProgrammePlaylist>(async () => {
		const raw = await unwrap(
			api.GET('/api/v2/programmes/{programme_id}/playlist', {
				params: { path: { programme_id: programmeId } }
			})
		);
		return (raw as unknown as { playlist: ProgrammePlaylist }).playlist;
	});

	let designs = $state<DesignSummary[]>([]);
	let designId = $state<number | null>(null);
	async function loadTicketDesign() {
		try {
			const [listRes, current] = await Promise.all([
				api.GET('/api/v2/tickets/designs'),
				api.GET('/api/v2/tickets/programmes/{programme_id}/design', {
					params: { path: { programme_id: programmeId } }
				})
			]);
			designs = listRes.data ?? [];
			designId = current.data?.design_id ?? null;
		} catch (e) {
			console.error('Failed to load ticket design', e);
		}
	}

	$effect(() => {
		void programmeId;
		if (isNew) return;
		void prog.load();
		void playlist.load();
		void loadTicketDesign();
	});

	function reloadAll() {
		void prog.load();
		void playlist.load();
	}

	const programme = $derived(prog.data?.programme);
	const items = $derived((programme?.items ?? []) as unknown as ProgrammeItem[]);

	const billItems = $derived(
		items.filter(
			(it) => (it.type === 'movie' && !it.details?.missing) || it.type === 'random_movie'
		)
	);
	const missingItems = $derived(items.filter((it) => it.details?.missing));

	let movieDetails = $state<Record<number, MovieDetail>>({});
	$effect(() => {
		const ids = billItems
			.map((it) => it.details?.movie_id)
			.filter((id): id is number => typeof id === 'number');
		for (const id of ids) {
			if (movieDetails[id]) continue;
			unwrap(api.GET('/api/v2/movies/{movie_id}', { params: { path: { movie_id: id } } }))
				.then((detail) => {
					if (detail) movieDetails = { ...movieDetails, [id]: detail };
				})
				.catch(() => {});
		}
	});
	const genres = query(() => unwrap(api.GET('/api/v2/movies/genres')));
	$effect(() => {
		if (isNew) return;
		void genres.load();
	});
	function genreNamesFor(detail: MovieDetail | null): string[] {
		const list = genres.data ?? [];
		return (detail?.genres ?? []).map((id) => list.find((g) => g.id === id)?.name ?? String(id));
	}
	function detailFor(item: ProgrammeItem): MovieDetail | null {
		const id = item.details?.movie_id;
		return typeof id === 'number' ? (movieDetails[id] ?? null) : null;
	}

	const grouped = $derived.by(() => {
		const byBlock = new Map<number, ProgrammePlaylistItem[]>();
		const unattached: ProgrammePlaylistItem[] = [];
		for (const pi of playlist.data?.items ?? []) {
			const blockId = pi.details?.programme_block_id;
			if (blockId === null || blockId === undefined) unattached.push(pi);
			else {
				if (!byBlock.has(blockId)) byBlock.set(blockId, []);
				byBlock.get(blockId)!.push(pi);
			}
		}
		return { byBlock, unattached };
	});

	const playlistCount = $derived(playlist.data?.items.length ?? 0);

	const endsAt = $derived(
		programme ? formatClock(new Date(Date.now() + programme.total_runtime * 60000)) : ''
	);

	// Bill collapse is NOT persisted: a working mode for this session, not a setting.
	let billCollapsed = $state(false);
	let autoCollapsed = false;
	$effect(() => {
		// Take the width once on first edit; after that the user's choice stands.
		if (editing && !autoCollapsed) {
			autoCollapsed = true;
			billCollapsed = true;
		}
	});

	let asideHeight = $state(0);
	let innerHeight = $state(0);
	const asideSticks = $derived(innerHeight > 0 && asideHeight + 120 <= innerHeight);

	// Tabs — the active one lives in ?tab=.
	const TABS = [
		{ id: 'rundown', label: 'Rundown' },
		{ id: 'tickets', label: 'Tickets' },
		{ id: 'title', label: 'Title screen' }
	];
	const tab = $derived.by(() => {
		const wanted = page.url.searchParams.get('tab');
		return TABS.some((t) => t.id === wanted) ? wanted! : 'rundown';
	});
	function selectTab(id: string) {
		if (id === tab) return;
		// A history entry per tab, so Back returns to the previous one.
		void goto(`${base}/programmes/${programmeId}?tab=${id}`, { noScroll: true, keepFocus: true });
	}
	const panelId = (id: string) => `panel-${id}`;

	// Edit mode (?edit=1): the URL carries it the way it carries the tab, so
	// reload, Back and a link all land in the same state.
	const editing = $derived(page.url.searchParams.get('edit') === '1');
	let editorDirty = $state(false);
	let confirmDlg = $state<ConfirmDialog>();
	let editorRef = $state<ProgrammeEditor>();

	function setEditing(on: boolean): void {
		const url = new URL(page.url);
		if (on) {
			url.searchParams.set('edit', '1');
			url.searchParams.set('tab', 'rundown');
		} else {
			url.searchParams.delete('edit');
		}
		void goto(url.pathname + url.search, { noScroll: true, keepFocus: true });
	}

	async function stopEditing(): Promise<void> {
		if (!editorDirty) {
			setEditing(false);
			return;
		}
		const ok = await confirmDlg?.confirm('The running order has unsaved changes. Discard them?', {
			confirmLabel: 'Discard',
			title: 'Discard changes'
		});
		if (ok) discardAndStop();
	}

	// Tell the editor first, so its navigation guard doesn't ask again on the way out.
	function discardAndStop(): void {
		editorRef?.discardChanges();
		setEditing(false);
	}

	function afterSave(): void {
		void prog.refresh();
		void playlist.load();
	}

	const SEGMENT_BASE =
		'flex h-8 min-w-0 flex-1 items-center justify-center gap-1.5 px-2 text-[0.8rem] ' +
		'font-medium whitespace-nowrap transition-colors hover:bg-surface-2';
	const segment = `${SEGMENT_BASE} text-text`;
	// Written out rather than appended: two text-colour utilities in one class
	// attribute are settled by the stylesheet's order, not the attribute's.
	const segmentActive = `${SEGMENT_BASE} bg-surface-3 text-accent`;

	let tracksOpen = $state(false);
	let tracksBlockId = $state<number | null>(null);
	const tracksItem = $derived(billItems.find((it) => it.id === tracksBlockId) ?? null);
	function openTracks(item: ProgrammeItem) {
		tracksBlockId = item.id;
		tracksOpen = true;
	}

	let cueing = $state(false);

	async function confirmRegen(): Promise<void> {
		const ok = await confirmDlg?.confirm(
			'Regenerate the playlist? Trailer rules and random selections will be re-picked.',
			{ confirmLabel: 'Regenerate', title: 'Regenerate playlist', danger: false }
		);
		if (ok) await regeneratePlaylist();
	}

	async function confirmDelete(): Promise<void> {
		if (!programme) return;
		const ok = await confirmDlg?.confirm(`Delete “${programme.name}”? This cannot be undone.`, {
			confirmLabel: 'Delete',
			title: 'Delete programme'
		});
		if (ok) await deleteProgramme();
	}

	async function cueAndOpenConsole() {
		if (cueing) return;
		cueing = true;
		try {
			const data = await unwrap(
				api.POST('/api/v2/playout/load', {
					body: { programme_id: programmeId, generate_playlist: true }
				})
			);
			const warnings = data?.warnings ?? [];
			if (warnings.length) {
				// Hand warnings to the remote page — a toast here is lost in the nav.
				sessionStorage.setItem('playout:preflightWarnings', JSON.stringify(warnings));
			}
			void goto(`${base}/remote`);
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Failed to cue programme', 'error');
			cueing = false;
		}
	}

	async function regeneratePlaylist() {
		try {
			// Message-only response (no data envelope) — check the error branch.
			const res = await api.POST('/api/v2/programmes/{programme_id}/regenerate-playlist', {
				params: { path: { programme_id: programmeId } }
			});
			if (res.error) throw toApiError(res.error, res.response);
			showToast('Playlist regenerated', 'success');
			reloadAll();
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Failed to regenerate playlist', 'error');
		}
	}

	async function deleteProgramme() {
		try {
			const res = await api.DELETE('/api/v2/programmes/{programme_id}', {
				params: { path: { programme_id: programmeId } }
			});
			if (res.error) throw toApiError(res.error, res.response);
			invalidate('programmes');
			void goto(`${base}/programmes`);
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Failed to delete programme', 'error');
		}
	}
</script>

<svelte:head>
	<title>{isNew ? 'New programme' : (programme?.name ?? 'Programme')} - Cinefin</title>
</svelte:head>
<svelte:window bind:innerHeight />

<div class="mb-4 flex flex-wrap items-center gap-2">
	<Button href="{base}/programmes" variant="ghost" size="sm">
		<ArrowLeft size={14} /> Programmes
	</Button>
	{#if isNew}
		<h1 class="text-lg font-semibold">New programme</h1>
	{/if}
</div>

{#if isNew}
	<div class="border border-border bg-surface-1">
		<ProgrammeEditor
			programmeId={null}
			items={handedOverFilms}
			onsaved={(id) => void goto(`${base}/programmes/${id}?edit=1`)}
		/>
	</div>
{:else if prog.loading}
	<Spinner label="Loading programme…" />
{:else if prog.error}
	<ErrorState error={prog.error} retry={() => reloadAll()} />
{:else if programme}
	<div class="flex flex-col gap-6 lg:flex-row lg:items-start">
		<aside
			bind:clientHeight={asideHeight}
			class="min-w-0 lg:shrink-0 lg:transition-[width] lg:duration-panel lg:ease-panel
				{billCollapsed ? 'lg:w-14' : 'lg:w-[30rem]'}
				{asideSticks ? 'lg:sticky lg:top-20' : ''}"
		>
			<button
				type="button"
				class="hidden w-full flex-col items-center gap-2 border border-border bg-surface-1 p-2
					text-faint transition-colors hover:border-border-strong hover:text-text
					{billCollapsed ? 'lg:flex' : ''}"
				aria-label="Show the bill"
				title="Show the bill"
				onclick={() => (billCollapsed = false)}
			>
				<PanelLeftOpen size={14} aria-hidden="true" />
				{#each billItems as item (item.id)}
					{@const poster = detailFor(item)?.thumbnail_url}
					{#if poster}
						<img src={poster} alt="" class="aspect-[2/3] w-full object-cover" />
					{:else}
						<span
							class="flex aspect-[2/3] w-full items-center justify-center border border-border
								bg-surface-2 font-mono text-[0.6rem] text-faint"
							title={item.title}
						>
							{item.type === 'random_movie' ? '??' : '-'}
						</span>
					{/if}
				{/each}
			</button>

			<div class="space-y-4 {billCollapsed ? 'lg:hidden' : ''}">
				<section class="border border-border bg-surface-1">
					<div class="p-4">
						<h1 class="text-xl leading-tight font-semibold">{programme.name}</h1>
						{#if programme.description}
							<p class="mt-1.5 text-sm text-muted">{programme.description}</p>
						{/if}
						<p class="mt-2 text-sm text-muted">
							{formatLongRuntime(programme.total_runtime)}
							<span class="mx-1 text-faint">·</span>
							{items.length} items
							{#if programme.template_id}
								<span class="mx-1 text-faint">·</span>
								<a
									href="{base}/templates/{programme.template_id}"
									class="text-accent hover:underline"
									title="Open this template in the editor"
								>
									{programme.template_name}
								</a>
							{/if}
							<span class="mx-1 text-faint">·</span>
							<span title="If started now, ends {endsAt}">
								ends <span class="font-mono text-text">{endsAt}</span>
							</span>
						</p>

						<Button
							variant="primary"
							class="mt-4 w-full"
							disabled={cueing}
							title="Cue in playout (doesn't start) and open the console"
							onclick={() => void cueAndOpenConsole()}
						>
							<Upload size={14} />
							{cueing ? 'Cueing…' : 'Cue & open console'}
						</Button>

						<div
							class="mt-2 flex divide-x divide-border overflow-hidden rounded-md
							border border-border-strong"
						>
							<a
								href="{base}/schedules?new={programmeId}"
								class={segment}
								title="Schedule a screening of this programme"
							>
								<CalendarPlus size={14} /> Schedule
							</a>
							<button
								type="button"
								class={editing ? segmentActive : segment}
								aria-pressed={editing}
								title={editing ? 'Stop editing the running order' : 'Edit the running order'}
								onclick={() => void (editing ? stopEditing() : setEditing(true))}
							>
								<Pencil size={14} /> Edit
							</button>
							<button
								type="button"
								class={segment}
								title="Regenerate the playlist - trailer rules and random selections will be re-picked"
								onclick={() => void confirmRegen()}
							>
								<RefreshCw size={14} /> Regenerate
							</button>
						</div>
					</div>

					<div class="flex justify-end border-t border-border px-4 py-2">
						<button
							type="button"
							class="inline-flex items-center gap-1.5 text-xs text-faint transition-colors
							hover:text-danger"
							onclick={() => void confirmDelete()}
						>
							<Trash2 size={12} /> Delete programme
						</button>
					</div>
				</section>
				{#each billItems as item (item.id)}
					<FeaturePanel
						{item}
						detail={detailFor(item)}
						genreNames={genreNamesFor(detailFor(item))}
						onopentracks={() => openTracks(item)}
					/>
				{/each}
			</div>
		</aside>

		<div class="min-w-0 flex-1 space-y-4">
			{#if programme.playlist_stale}
				<Banner severity="warning" title="The playlist couldn't be updated automatically.">
					Playback would use the previous version - regenerate it to pick up your latest changes.
					{#snippet actions()}
						<button
							type="button"
							class="font-medium text-warning hover:underline"
							onclick={() => void confirmRegen()}
						>
							Regenerate playlist
						</button>
					{/snippet}
				</Banner>
			{/if}

			{#if missingItems.length}
				{@const n = missingItems.length}
				{@const titles = missingItems
					.map((it) => it.title)
					.filter((t) => t && t !== 'Movie no longer in library')}
				<Banner severity="danger">
					<strong>
						{n}
						{n === 1 ? 'movie is' : 'movies are'} no longer in your library{titles.length
							? ` (${titles.join(', ')})`
							: ''}.
					</strong>
					{n === 1 ? 'This block' : 'These blocks'} will be skipped when the playlist is generated - edit
					the programme to replace {n === 1 ? 'it' : 'them'}.
					{#snippet actions()}
						<button
							type="button"
							class="font-medium text-danger hover:underline"
							onclick={() => setEditing(true)}
						>
							Edit programme
						</button>
					{/snippet}
				</Banner>
			{/if}

			<section class="border border-border bg-surface-1">
				<!-- The header's hairline is an inset line, like the tab strip's, so the two coincide. -->
				<header
					class="flex flex-wrap items-center justify-between gap-x-4 px-3
						shadow-[inset_0_-1px_0_var(--color-border)]"
				>
					<div class="flex min-w-0 items-center gap-1">
						<AsideToggle
							collapsed={billCollapsed}
							label="the bill"
							ontoggle={() => (billCollapsed = !billCollapsed)}
						/>
						<Tabs
							tabs={TABS}
							value={tab}
							{panelId}
							onselect={selectTab}
							label="Programme sections"
						/>
					</div>
					{#if tab === 'rundown' && !editing}
						<span class="py-2 font-mono text-xs text-muted">
							{items.length} items · {playlistCount} playlist entries · {formatLongRuntime(
								programme.total_runtime
							)}
						</span>
					{/if}
				</header>

				<div
					id={panelId('rundown')}
					role="tabpanel"
					aria-labelledby="tab-rundown"
					hidden={tab !== 'rundown'}
				>
					{#if editing}
						<!-- Keyed on the id so switching programmes never edits the previous one's blocks. -->
						{#key programmeId}
							<ProgrammeEditor
								bind:this={editorRef}
								{programmeId}
								items={programme.items as unknown as never}
								initialName={programme.name}
								initialDescription={programme.description ?? ''}
								bind:dirty={editorDirty}
								onsaved={afterSave}
							>
								{#snippet actions()}
									<Button size="sm" title="Stop editing" onclick={() => void stopEditing()}>
										<Check size={13} /> Done
									</Button>
								{/snippet}
							</ProgrammeEditor>
						{/key}
					{:else}
						<Rundown
							{programmeId}
							{items}
							byBlock={grouped.byBlock}
							unattached={grouped.unattached}
							onedit={() => setEditing(true)}
						/>
					{/if}
				</div>

				<div
					id={panelId('tickets')}
					role="tabpanel"
					aria-labelledby="tab-tickets"
					hidden={tab !== 'tickets'}
				>
					<TicketsPanel
						{programmeId}
						programmeName={programme.name}
						{designs}
						{designId}
						onchange={(id) => (designId = id)}
					/>
				</div>

				<div
					id={panelId('title')}
					role="tabpanel"
					aria-labelledby="tab-title"
					hidden={tab !== 'title'}
				>
					<TitleConfigCard {programme} onsaved={() => void prog.refresh()} />
				</div>
			</section>
		</div>
	</div>

	<TracksDialog
		bind:open={tracksOpen}
		{programmeId}
		blockId={tracksBlockId}
		title={tracksItem?.title ?? ''}
		detail={tracksItem ? detailFor(tracksItem) : null}
		audioIndex={tracksItem?.details?.audio_track ?? null}
		subtitleIndex={tracksItem?.details?.subtitle_track ?? null}
		onsaved={() => void prog.refresh()}
	/>
{/if}

<ConfirmDialog bind:this={confirmDlg} />
