<script lang="ts">
	// /programmes/new. Start from a template: its running order, filled with the chosen movies and
	// laid out by the server (create-from-template), so trailer matching and certification cards
	// come out exactly as the template says. Or start from Blank: the editor, with the movies in.
	import { untrack } from 'svelte';
	import { Check, Dices, Film, ListVideo, Plus, TriangleAlert, X } from '@lucide/svelte';
	import { base } from '$app/paths';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { api, unwrap } from '$lib/api/client';
	import { Query, query } from '$lib/api/query.svelte';
	import { attempt } from '$lib/settings/form.svelte';
	import { showToast } from '$lib/toast.svelte';
	import { invalidate } from '$lib/invalidate';
	import { formatRuntime } from '$lib/format';
	import {
		featureBlocks,
		itemTitle,
		movieCount,
		type RandomSlot,
		type SelectedFilm,
		type SelectedItem
	} from '$lib/programmes/create-types';
	import {
		buildRundown,
		featureItems,
		previewWarnings,
		slotFeatureNumbers,
		type ProgrammePreview,
		type TemplateDetail
	} from '$lib/programmes/create-rundown';
	import type { ProgrammeItemIn } from '$lib/editor/programme-adapter';
	import TemplateCard from '$lib/programmes/TemplateCard.svelte';
	import RandomPickDialog from '$lib/programmes/RandomPickDialog.svelte';
	import ProgrammeEditor from '$lib/programmes/ProgrammeEditor.svelte';
	import SlotRow from '$lib/programmes/new-SlotRow.svelte';
	import SupportRow from '$lib/programmes/new-SupportRow.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import PickerDialog from '$lib/editor/PickerDialog.svelte';
	import { fetchMovieDetail } from '$lib/editor/pick-actions';

	let features = $state<SelectedItem[]>([]);
	let loading = $state(true);

	const templates = query(() =>
		unwrap(api.GET('/api/v2/templates/list', { params: { query: { per_page: 100 } } }))
	);
	const allTemplates = $derived(templates.data?.templates ?? []);
	const fits = (n: number) => features.length > 0 && n === features.length;
	const orderedTemplates = $derived([
		...allTemplates.filter((t) => fits(t.number_of_features)),
		...allTemplates.filter((t) => !fits(t.number_of_features))
	]);

	// null = nothing chosen yet; 'blank' = the editor.
	let choice = $state<number | 'blank' | null>(null);
	const templateId = $derived(typeof choice === 'number' ? choice : null);
	const selectedTemplate = $derived(allTemplates.find((t) => t.id === templateId) ?? null);

	const detailQuery = new Query(async () => {
		const path = { template_id: templateId! };
		return (await unwrap(api.GET('/api/v2/templates/{template_id}', { params: { path } })))
			.template;
	});
	// Kept while the next template loads; dropped with the choice or on a failed load.
	const detail = $derived<TemplateDetail | null>(
		(templateId && !detailQuery.error && detailQuery.data) || null
	);
	const slotCount = $derived(featureItems(detail).length);

	// The movies at the moment Blank was chosen; the editor owns them from then on.
	let blankItems = $state.raw<ProgrammeItemIn[]>([]);
	let blankName = $state('');
	let blankDescription = $state('');
	let editorDirty = $state(false);
	let confirmDialog = $state<ConfirmDialog>();

	async function choose(next: number | 'blank'): Promise<void> {
		if (next === choice) return;
		if (choice === 'blank' && editorDirty) {
			const ok = await confirmDialog?.confirm(
				'The running order you laid out by hand will be lost.',
				{ confirmLabel: 'Discard it' }
			);
			if (!ok) return;
		}
		if (next === 'blank') {
			blankItems = featureBlocks(features);
			blankName = name;
			blankDescription = description;
		}
		choice = next;
		if (typeof next === 'number') void detailQuery.load();
	}

	// A template that takes exactly the movies handed over is chosen for you; with no templates
	// at all, Blank is the only start there is.
	$effect(() => {
		if (loading || templates.loading || templates.error || choice !== null) return;
		const fit = allTemplates.find((t) => fits(t.number_of_features));
		if (fit || !allTemplates.length) untrack(() => void choose(fit?.id ?? 'blank'));
	});

	void initialLoad();

	// Hand-offs from the library: ?movies=1,2 and ?random_movies=[…].
	async function initialLoad(): Promise<void> {
		try {
			const params = page.url.searchParams;
			const movieIds = (params.get('movies') || '')
				.split(',')
				.map((s) => parseInt(s.trim(), 10))
				.filter((n) => !Number.isNaN(n));

			let randoms: RandomSlot[] = [];
			const randomParam = params.get('random_movies');
			if (randomParam) {
				try {
					const parsed = JSON.parse(randomParam) as Partial<RandomSlot>[];
					randoms = parsed.map((c, i) => ({
						kind: 'random',
						id: c.id ?? Date.now() + i,
						label: c.label ?? null,
						genre_ids: c.genre_ids ?? [],
						genre_names: c.genre_names ?? [],
						certification: c.certification ?? null,
						year_from: c.year_from ?? null,
						year_to: c.year_to ?? null,
						runtime_from: c.runtime_from ?? null,
						runtime_to: c.runtime_to ?? null
					}));
				} catch (e) {
					console.error('Error parsing random_movies:', e);
				}
			}

			const films = await Promise.all(movieIds.map((id) => loadFilm(id)));
			features = [...films.filter((f): f is SelectedFilm => f !== null), ...randoms];
		} finally {
			loading = false;
		}
	}

	async function loadFilm(movieId: number): Promise<SelectedFilm | null> {
		try {
			const m = await fetchMovieDetail(movieId);
			return {
				kind: 'movie',
				id: m.id,
				title: m.title,
				year: m.year ?? null,
				runtime: m.runtime ?? null,
				certification: m.certification ?? null,
				thumbnail_url: m.thumbnail_url ?? null,
				director: m.director ?? null,
				description: m.description ?? null,
				genre_ids: m.genres ?? [],
				resolution: m.resolution ?? null,
				video_codec: m.video_info?.codec ?? null,
				audio_tracks: m.audio_tracks ?? [],
				subtitle_tracks: m.subtitle_tracks ?? [],
				audio_track_index: 0,
				subtitle_track_index: null
			};
		} catch (e) {
			console.error(`Error loading movie ${movieId}:`, e);
			showToast('Failed to load movie information', 'error');
			return null;
		}
	}

	let moviePicker = $state<PickerDialog>();
	let addPicker = $state<PickerDialog>();

	async function addFilm(id: number): Promise<void> {
		const film = await loadFilm(id);
		if (film) features.push(film);
	}

	// A slot past the last movie is an empty one: filling it appends.
	function place(index: number, item: SelectedItem): void {
		if (index >= features.length) features.push(item);
		else features[index] = item;
	}

	async function chooseFilm(index: number): Promise<void> {
		const picked = await moviePicker?.pick();
		if (!picked) return;
		const film = await loadFilm(picked.id);
		if (film) place(index, film);
	}

	function moveFeature(index: number, direction: number): void {
		const target = index + direction;
		if (target < 0 || target >= features.length) return;
		[features[index], features[target]] = [features[target], features[index]];
	}

	let randomOpen = $state(false);
	// null = a new pick appended; a number = that slot's pick.
	let randomIndex = $state<number | null>(null);
	let randomInitial = $state<RandomSlot | null>(null);

	function editRandom(index: number | null): void {
		randomIndex = index;
		const current = index === null ? null : features[index];
		randomInitial = current?.kind === 'random' ? current : null;
		randomOpen = true;
	}

	function applyRandom(slot: RandomSlot): void {
		place(randomIndex ?? features.length, slot);
		randomIndex = null;
	}

	// Name / description: auto-filled until the user types their own.
	let name = $state('');
	let description = $state('');
	let nameEdited = $state(false);
	let descEdited = $state(false);

	const autoName = $derived(features.map(itemTitle).join(' / '));
	const autoDescription = $derived.by(() => {
		if (!features.length) return '';
		if (features.length === 1) {
			const it = features[0];
			const year = it.kind === 'movie' && it.year ? ` (${it.year})` : '';
			return `Cinema screening of ${itemTitle(it)}${year}`;
		}
		return features
			.map((it) => `${itemTitle(it)} (${(it.kind === 'movie' && it.year) || 'Unknown'})`)
			.join(', ');
	});
	$effect(() => {
		if (!nameEdited) name = autoName;
	});
	$effect(() => {
		if (!descEdited) description = autoDescription;
	});

	// Keyed by the template's own feature numbering, as create-from-template expects.
	function buildMoviesPayload(): Record<string, Record<string, unknown>> {
		const numbers = slotFeatureNumbers(detail);
		const movies: Record<string, Record<string, unknown>> = {};
		features.forEach((item, index) => {
			const key = String(numbers[index] ?? index + 1);
			movies[key] =
				item.kind === 'random'
					? {
							type: 'random_movie',
							genre_ids: item.genre_ids.length ? item.genre_ids : null,
							certification: item.certification || null,
							year_from: item.year_from || null,
							year_to: item.year_to || null,
							runtime_from: item.runtime_from || null,
							runtime_to: item.runtime_to || null
						}
					: {
							id: item.id,
							title: item.title,
							audio_track_index: item.audio_track_index || 0,
							subtitle_track_index: item.subtitle_track_index
						};
		});
		return movies;
	}

	const ready = $derived(!!detail && features.length === slotCount);

	// Debounced and sequence-guarded; the last good preview stays while the next is fetched.
	let preview = $state<ProgrammePreview | null>(null);
	let previewFailed = $state(false);
	let previewSeq = 0;

	$effect(() => {
		const template = templateId;
		const movies = buildMoviesPayload();
		if (!template || !ready) {
			preview = null;
			previewFailed = false;
			return;
		}
		const seq = ++previewSeq;
		const timer = setTimeout(async () => {
			try {
				const data = await unwrap(
					api.POST('/api/v2/programmes/create-from-template', {
						body: { name: 'Preview', description: '', template_id: template, movies, preview: true }
					})
				);
				if (seq !== previewSeq) return;
				const p = (data as unknown as { programme?: ProgrammePreview }).programme;
				if (p) {
					preview = p;
					previewFailed = false;
				}
			} catch (e) {
				if (seq !== previewSeq) return;
				console.error('Error building the preview:', e);
				preview = null;
				previewFailed = true;
			}
		}, 400);
		return () => clearTimeout(timer);
	});

	const rows = $derived(buildRundown(detail, features, preview));
	const warnings = $derived(previewWarnings(preview));
	const estimated = $derived(rows.some((r) => r.estimated && r.runtime !== null));

	let creating = $state(false);

	async function createProgramme(): Promise<void> {
		if (!ready || !name.trim() || creating) return;
		creating = true;
		await attempt(async () => {
			const data = await unwrap(
				api.POST('/api/v2/programmes/create-from-template', {
					body: {
						name: name.trim(),
						description: description.trim(),
						template_id: templateId!,
						movies: buildMoviesPayload(),
						preview: false
					}
				})
			);
			const result = data as unknown as { id?: number; playlist_generated?: boolean | null };
			if (!result.id) {
				showToast('Could not create the programme', 'error');
				return;
			}
			invalidate('programmes');
			if (result.playlist_generated === false) {
				showToast('Programme created, but its playlist could not be generated', 'warning');
			} else {
				showToast('Programme created', 'success');
			}
			await goto(`${base}/programmes/${result.id}`);
		}, 'Could not create the programme - try again');
		creating = false;
	}
</script>

{#snippet heading(title: string, note: string)}
	<div class="flex flex-wrap items-baseline gap-2 text-sm font-semibold">
		<h2>{title}</h2>
		<span class="font-normal text-muted">{note}</span>
	</div>
{/snippet}

{#if loading}
	<Spinner label="Loading movies…" />
{:else}
	<section class="border border-border bg-surface-1 p-4" aria-label="Start from">
		{@render heading(
			'Start from',
			'A template lays the running order out around your movies; you can change anything after.'
		)}

		{#if templates.loading}
			<Spinner label="Loading templates…" size="sm" />
		{:else if templates.error}
			<ErrorState error={templates.error} retry={() => void templates.load()} compact />
		{:else}
			<div class="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
				<button
					type="button"
					class="flex min-w-0 flex-col gap-1.5 border bg-surface-2 p-3 text-left transition-colors
						{choice === 'blank' ? 'border-accent' : 'border-border hover:border-border-strong'}"
					aria-pressed={choice === 'blank'}
					onclick={() => void choose('blank')}
				>
					<span class="flex w-full items-start gap-2 text-sm font-semibold">
						<span class="min-w-0 flex-1">Blank</span>
						{#if choice === 'blank'}<Check size={14} class="text-accent" />{/if}
					</span>
					<span class="text-xs text-muted">An empty running order, laid out by hand</span>
				</button>
				{#each orderedTemplates as template (template.id)}
					<TemplateCard
						{template}
						selected={choice === template.id}
						note={features.length && !fits(template.number_of_features)
							? `Takes ${movieCount(template.number_of_features)} - you have ${features.length}`
							: undefined}
						onselect={() => void choose(template.id)}
					/>
				{/each}
			</div>
			{#if !allTemplates.length}
				<p class="mt-2 text-xs text-muted">
					No templates yet - a template is a reusable running order.
					<a class="text-accent hover:underline" href="{base}/templates/new">Create a template</a>
				</p>
			{/if}
		{/if}

		{#if choice !== 'blank'}
			<div class="mt-4 border-t border-border pt-3">
				{@render heading(
					'Movies',
					selectedTemplate
						? `${selectedTemplate.name} has ${movieCount(slotCount || selectedTemplate.number_of_features)} to fill`
						: 'What the programme is built around'
				)}
				<div class="mt-2 flex flex-wrap items-center gap-2">
					{#each features as item, index (item.kind === 'random' ? `r${item.id}` : `m${item.id}-${index}`)}
						<span
							class="inline-flex h-8 max-w-64 items-center gap-1.5 border border-border bg-surface-2
								pr-1 pl-2.5 text-sm"
						>
							{#if item.kind === 'random'}
								<Dices size={13} class="shrink-0 text-faint" />
							{:else}
								<Film size={13} class="shrink-0 text-faint" />
							{/if}
							<span class="truncate">{itemTitle(item)}</span>
							<button
								type="button"
								class="rounded-sm p-1 text-faint hover:bg-surface-3 hover:text-text"
								aria-label="Remove {itemTitle(item)}"
								onclick={() => features.splice(index, 1)}
							>
								<X size={12} />
							</button>
						</span>
					{/each}
					<Button size="sm" onclick={() => addPicker?.show()}>
						<Plus size={13} /> Add movies
					</Button>
					<Button
						size="sm"
						title="Add a feature drawn at random from filters when the playlist is generated"
						onclick={() => editRandom(null)}
					>
						<Dices size={13} /> Add a random movie
					</Button>
				</div>
			</div>
		{/if}
	</section>

	{#if choice === 'blank'}
		<div class="mt-6 border border-border bg-surface-1">
			<ProgrammeEditor
				programmeId={null}
				items={blankItems}
				initialName={blankName}
				initialDescription={blankDescription}
				bind:dirty={editorDirty}
				onsaved={(id) => void goto(`${base}/programmes/${id}?edit=1`)}
			/>
		</div>
	{:else if templateId}
		<section class="mt-6">
			<div class="flex flex-col gap-3 sm:flex-row">
				<label class="flex min-w-0 flex-1 flex-col gap-1 text-sm" for="np-name">
					<span class="font-medium">Name</span>
					<Input
						id="np-name"
						placeholder={autoName || 'Programme name'}
						bind:value={name}
						oninput={() => (nameEdited = true)}
					/>
				</label>
				<label class="flex min-w-0 flex-1 flex-col gap-1 text-sm" for="np-description">
					<span class="font-medium">Description</span>
					<Input
						id="np-description"
						placeholder={autoDescription || 'Optional'}
						bind:value={description}
						oninput={() => (descEdited = true)}
					/>
				</label>
			</div>

			<div class="mt-5 border-b border-border pb-2">
				{@render heading('Running order', selectedTemplate?.name ?? '')}
			</div>
			{#if detailQuery.loading && !detail}
				<Spinner label="Laying out the running order…" size="sm" />
			{:else if detailQuery.error}
				<ErrorState
					message="Could not load the template's running order."
					retry={() => void detailQuery.load()}
					compact
				/>
			{:else if !rows.length}
				<p class="mt-3 text-sm text-muted">This template has no items yet.</p>
			{:else}
				<ol class="divide-y divide-border">
					{#each rows as row (row.key)}
						<li>
							{#if row.kind === 'slot'}
								<SlotRow
									{row}
									slots={slotCount}
									onchoose={() => void chooseFilm(row.slotIndex)}
									onrandom={() => editRandom(row.slotIndex)}
									onmove={(dir) => moveFeature(row.slotIndex, dir)}
								/>
							{:else}
								<SupportRow {row} />
							{/if}
						</li>
					{/each}
				</ol>
			{/if}

			<div
				class="sticky bottom-0 z-[5] mt-6 -mx-4 -mb-4 flex flex-wrap items-center gap-x-4 gap-y-2
					border-t border-border bg-bg px-4 py-3 md:-mx-6 md:-mb-6 md:px-6"
			>
				<div class="min-w-0 text-sm" aria-live="polite">
					{#if detail && features.length > slotCount}
						<p class="flex items-center gap-1.5 text-warning">
							<TriangleAlert size={13} class="shrink-0" />
							{selectedTemplate?.name} takes {movieCount(slotCount)} - remove {features.length -
								slotCount}, or pick another template.
						</p>
					{:else if detail && !ready}
						<p class="text-faint">Fill every feature slot to create the programme.</p>
					{:else if previewFailed}
						<p class="flex items-center gap-1.5 text-warning">
							<TriangleAlert size={13} class="shrink-0" />
							Couldn't work out the running order - change the template or movies to try again.
						</p>
					{:else if preview}
						<p class="font-mono text-muted">
							{preview.total_blocks} items · {estimated ? '≈ ' : ''}{formatRuntime(
								preview.total_runtime
							)}
						</p>
						{#each warnings as warning (warning)}
							<p class="mt-0.5 flex items-start gap-1.5 text-xs text-warning">
								<TriangleAlert size={12} class="mt-0.5 shrink-0" />
								{warning}
							</p>
						{/each}
					{:else if ready}
						<Spinner label="Working out the running order…" size="sm" />
					{/if}
				</div>
				<Button
					class="ml-auto"
					variant="primary"
					disabled={!ready || !name.trim() || creating}
					onclick={() => void createProgramme()}
				>
					<ListVideo size={14} />
					{creating ? 'Creating…' : 'Create programme'}
				</Button>
			</div>
		</section>
	{:else}
		<p class="mt-6 text-sm text-muted">
			Pick a template above, or Blank to lay the running order out by hand.
		</p>
	{/if}
{/if}

<RandomPickDialog bind:open={randomOpen} initial={randomInitial} onconfirm={applyRandom} />
<ConfirmDialog bind:this={confirmDialog} title="Start over?" />
<PickerDialog kind="movie" bind:this={moviePicker} />
<PickerDialog
	kind="movie"
	mode="multi"
	bind:this={addPicker}
	isSelected={(picked) => features.some((it) => it.kind === 'movie' && it.id === picked.id)}
	onadd={(picked) => addFilm(picked.id)}
/>
