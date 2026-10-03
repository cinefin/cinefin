<script lang="ts">
	import PageHeader from '$lib/components/shell/PageHeader.svelte';
	import {
		ArrowLeft,
		ArrowRight,
		CalendarPlus,
		ChevronDown,
		Dices,
		Eye,
		Film,
		LayoutTemplate,
		ListVideo,
		Plus,
		TriangleAlert,
		Upload
	} from '@lucide/svelte';
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
		movieCount,
		itemTitle,
		type RandomSlot,
		type SelectedFilm,
		type SelectedItem
	} from '$lib/programmes/create-types';
	import { stashFilmsForBlankEditor } from '$lib/programmes/blank-handoff';
	import {
		buildRundown,
		featureItems,
		previewWarnings,
		slotFeatureNumbers,
		type ProgrammePreview,
		type TemplateDetail
	} from '$lib/programmes/create-rundown';
	import Stepper from '$lib/programmes/create-Stepper.svelte';
	import FeatureCard from '$lib/programmes/create-FeatureCard.svelte';
	import TemplateCard from '$lib/programmes/TemplateCard.svelte';
	import RandomPickDialog from '$lib/programmes/RandomPickDialog.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Dialog from '$lib/components/ui/Dialog.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import PickerDialog from '$lib/editor/PickerDialog.svelte';
	import { fetchMovieDetail } from '$lib/editor/pick-actions';
	import SlotRow from './SlotRow.svelte';
	import SupportRow from './SupportRow.svelte';
	import TrackRadios from '$lib/programmes/TrackRadios.svelte';

	type Step = 'films' | 'template' | 'rundown';
	let step = $state<Step>('films');

	let features = $state<SelectedItem[]>([]);

	const templates = query(() =>
		unwrap(api.GET('/api/v2/templates/list', { params: { query: { per_page: 100 } } }))
	);
	const allTemplates = $derived(templates.data?.templates ?? []);

	let selectedTemplateId = $state<number | null>(null);
	const detailQuery = new Query(async () => {
		const path = { template_id: selectedTemplateId! };
		return (await unwrap(api.GET('/api/v2/templates/{template_id}', { params: { path } })))
			.template;
	});
	// Kept while the next template loads; dropped with the choice or on a failed load.
	const detail = $derived<TemplateDetail | null>(
		(selectedTemplateId && !detailQuery.error && detailQuery.data) || null
	);

	const selectedTemplate = $derived(allTemplates.find((t) => t.id === selectedTemplateId) ?? null);
	const slotCount = $derived(featureItems(detail).length);

	function fits(numberOfFeatures: number): boolean {
		return features.length > 0 && numberOfFeatures === features.length;
	}

	function startFromBlank() {
		stashFilmsForBlankEditor(features);
		void goto(`${base}/programmes/new`);
	}

	const fittingTemplates = $derived(allTemplates.filter((t) => fits(t.number_of_features)));
	const otherTemplates = $derived(allTemplates.filter((t) => !fits(t.number_of_features)));
	let showAllTemplates = $state(false);

	function templateNote(numberOfFeatures: number): string | undefined {
		if (fits(numberOfFeatures)) return undefined;
		const takes = numberOfFeatures === 1 ? '1 feature' : `${numberOfFeatures} features`;
		return `Takes ${takes} - you have ${movieCount(features.length)}`;
	}

	function selectTemplate(id: number): void {
		selectedTemplateId = id;
		step = 'rundown';
		void detailQuery.load();
	}

	// Adding/removing a feature can invalidate the chosen template: cleared here, with the reason.
	function invalidateTemplate(): void {
		if (!selectedTemplateId) return;
		if (selectedTemplate && fits(selectedTemplate.number_of_features)) return;
		const was = selectedTemplate?.name;
		selectedTemplateId = null;
		if (step === 'rundown') step = 'template';
		if (was) {
			showToast(`“${was}” doesn't take ${movieCount(features.length)} - pick a template`, 'info');
		}
	}

	let loading = $state(true);
	void initialLoad();

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
					type RandomConfig = Partial<RandomSlot> & {
						id: number;
						genre_id?: number | null;
						genre_name?: string | null;
					};
					// Legacy links were double-encoded.
					let json = randomParam;
					try {
						JSON.parse(json);
					} catch {
						json = decodeURIComponent(randomParam);
					}
					const parsed = JSON.parse(json) as RandomConfig[];
					randoms = parsed.map((c) => ({
						kind: 'random',
						id: c.id,
						label: c.label ?? null,
						genre_ids: c.genre_ids ?? (c.genre_id ? [c.genre_id] : []),
						genre_names: c.genre_names ?? (c.genre_name ? [c.genre_name] : []),
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

			// Legacy hand-off: the library page could stash a selection here.
			if (!movieIds.length && !randoms.length) {
				const stored = sessionStorage.getItem('selectedMovies');
				if (stored) {
					sessionStorage.removeItem('selectedMovies');
					try {
						const parsed = JSON.parse(stored) as { id: number }[];
						movieIds.push(...parsed.map((m) => m.id));
					} catch {
						/* corrupt stash — start empty */
					}
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
		if (!film) return;
		features.push(film);
		invalidateTemplate();
	}

	async function swapFilm(index: number): Promise<void> {
		const picked = await moviePicker?.pick();
		if (!picked) return;
		const film = await loadFilm(picked.id);
		if (film) features[index] = film;
	}

	function removeFeature(index: number): void {
		features.splice(index, 1);
		invalidateTemplate();
	}

	function moveFeature(index: number, direction: number): void {
		const target = index + direction;
		if (target < 0 || target >= features.length) return;
		[features[index], features[target]] = [features[target], features[index]];
	}

	function setAudio(index: number, trackIndex: number): void {
		const item = features[index];
		if (item?.kind === 'movie') item.audio_track_index = trackIndex;
	}

	function setSubtitle(index: number, trackIndex: number | null): void {
		const item = features[index];
		if (item?.kind === 'movie') item.subtitle_track_index = trackIndex;
	}

	// A draft, so Cancel leaves the film as it was.
	let tracksOpen = $state(false);
	let tracksIndex = $state<number | null>(null);
	let draftAudio = $state<number | null>(0);
	let draftSubtitle = $state<number | null>(null);
	const tracksFilm = $derived.by(() => {
		const item = tracksIndex === null ? null : features[tracksIndex];
		return item?.kind === 'movie' ? item : null;
	});

	function openTracks(index: number): void {
		const item = features[index];
		if (item?.kind !== 'movie') return;
		tracksIndex = index;
		draftAudio = item.audio_track_index;
		draftSubtitle = item.subtitle_track_index;
		tracksOpen = true;
	}

	function applyTracks(): void {
		if (tracksIndex !== null) {
			setAudio(tracksIndex, draftAudio ?? 0);
			setSubtitle(tracksIndex, draftSubtitle);
		}
		tracksOpen = false;
	}

	let randomOpen = $state(false);
	// null = a new pick appended; a number = that feature's pick edited.
	let randomIndex = $state<number | null>(null);
	let randomInitial = $state<RandomSlot | null>(null);

	function editRandom(index: number | null): void {
		randomIndex = index;
		const current = index === null ? null : features[index];
		randomInitial = current?.kind === 'random' ? current : null;
		randomOpen = true;
	}

	function applyRandom(slot: RandomSlot): void {
		if (randomIndex === null) {
			features.push(slot);
			invalidateTemplate();
		} else {
			features[randomIndex] = slot;
			randomIndex = null;
		}
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
			if (item.kind === 'random') {
				movies[key] = {
					type: 'random_movie',
					genre_ids: item.genre_ids.length ? item.genre_ids : null,
					certification: item.certification || null,
					year_from: item.year_from || null,
					year_to: item.year_to || null,
					runtime_from: item.runtime_from || null,
					runtime_to: item.runtime_to || null
				};
			} else {
				movies[key] = {
					id: item.id,
					title: item.title,
					audio_track_index: item.audio_track_index || 0,
					subtitle_track_index: item.subtitle_track_index
				};
			}
		});
		return movies;
	}

	// Debounced and sequence-guarded; the last good preview stays while the next is fetched.
	let preview = $state<ProgrammePreview | null>(null);
	let previewFailed = $state(false);
	let previewSeq = 0;

	const ready = $derived(!!selectedTemplateId && !!detail && features.length === slotCount);

	$effect(() => {
		const template = selectedTemplateId;
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
	let warningsOpen = $state(false);

	const estimated = $derived(rows.some((r) => r.estimated && r.runtime !== null));
	const itemCount = $derived(preview?.total_blocks ?? 0);

	const featuresRuntime = $derived(
		features.reduce((total, it) => total + (it.kind === 'movie' ? (it.runtime ?? 0) : 0), 0)
	);
	const anyEstimatedFeature = $derived(features.some((it) => it.kind === 'random'));

	const steps = $derived([
		{
			id: 'films',
			label: 'Movies',
			summary: features.length ? features.map(itemTitle).join(', ') : '',
			enabled: true,
			done: features.length > 0
		},
		{
			id: 'template',
			label: 'Template',
			summary: selectedTemplate?.name ?? '',
			enabled: features.length > 0,
			done: !!selectedTemplateId
		},
		{
			id: 'rundown',
			label: 'Running order',
			summary: preview ? `${itemCount} items · ${formatRuntime(preview.total_runtime)}` : '',
			enabled: ready,
			done: false
		}
	]);

	function goToStep(id: string): void {
		if (id === 'template' && !features.length) return;
		if (id === 'rundown' && !ready) return;
		step = id as Step;
	}

	let creating = $state(false);
	const canCreate = $derived(ready && !!name.trim());

	interface Created {
		id: number;
		playlist_generated?: boolean | null;
		playlist_items?: number | null;
		certifications_generated?: number | null;
	}
	let created = $state<Created | null>(null);
	let createdName = $state('');
	let createdOpen = $state(false);

	async function createProgramme(): Promise<void> {
		if (!ready) {
			showToast('Choose the movies and a template that takes them', 'error');
			return;
		}
		if (!name.trim()) {
			showToast('Please enter a programme name', 'warning');
			return;
		}
		creating = true;
		await attempt(async () => {
			const data = await unwrap(
				api.POST('/api/v2/programmes/create-from-template', {
					body: {
						name: name.trim(),
						description: description.trim(),
						template_id: selectedTemplateId!,
						movies: buildMoviesPayload(),
						preview: false
					}
				})
			);
			const result = data as unknown as Created;
			if (result.id) {
				created = result;
				createdName = name.trim();
				createdOpen = true;
				invalidate('programmes');
			} else {
				showToast('Could not create the programme', 'error');
			}
		}, 'Could not create the programme - try again');
		creating = false;
	}

	const createdSummary = $derived.by(() => {
		if (!created) return '';
		const bits = [`“${createdName}” is ready`];
		if (created.playlist_generated)
			bits.push(`playlist generated with ${created.playlist_items} items`);
		else if (created.playlist_generated === false) bits.push('warning: playlist generation failed');
		if (created.certifications_generated) {
			bits.push(
				`${created.certifications_generated} certification card${created.certifications_generated > 1 ? 's' : ''} generated`
			);
		}
		return bits.join(' - ') + '.';
	});

	let cueing = $state(false);
	async function cueCreated(): Promise<void> {
		if (!created || cueing) return;
		cueing = true;
		try {
			await unwrap(
				api.POST('/api/v2/playout/load', {
					body: { programme_id: created.id, generate_playlist: true }
				})
			);
			void goto(`${base}/remote`);
		} catch {
			showToast('Could not cue the programme', 'error');
			cueing = false;
		}
	}
</script>

{#snippet heading(title: string, note: string)}
	<div
		class="flex flex-wrap items-baseline gap-2 border-b border-border pb-2 text-sm font-semibold"
	>
		<h2>{title}</h2>
		<span class="font-normal text-muted">{note}</span>
	</div>
{/snippet}

{#snippet addButtons(variant: 'primary' | 'default' = 'default')}
	<Button {variant} onclick={() => addPicker?.show()}>
		<Plus size={14} /> Add movies
	</Button>
	<Button
		title="Add a feature drawn at random from filters when the playlist is generated"
		onclick={() => editRandom(null)}
	>
		<Dices size={14} /> Add a random movie
	</Button>
{/snippet}

<PageHeader title="Create programme" back={{ href: `${base}/programmes`, label: 'Programmes' }} />

{#if loading}
	<Spinner label="Loading movies…" />
{:else}
	<Stepper {steps} current={step} onselect={goToStep} />

	{#if step === 'films'}
		<section class="mt-6">
			{@render heading(
				'The movies',
				features.length
					? `${movieCount(features.length)} - in this order`
					: 'What the programme is built around'
			)}

			{#if features.length}
				<div class="mt-3 grid gap-3 grid-cols-[repeat(auto-fill,minmax(min(30rem,100%),1fr))]">
					{#each features as item, index (item.kind === 'random' ? `r${item.id}` : `m${item.id}-${index}`)}
						<FeatureCard
							{item}
							position={index + 1}
							count={features.length}
							onswap={() => void swapFilm(index)}
							onfilters={() => editRandom(index)}
							onremove={() => removeFeature(index)}
							onmove={(dir) => moveFeature(index, dir)}
							onaudio={(i) => setAudio(index, i)}
							onsubtitle={(i) => setSubtitle(index, i)}
						/>
					{/each}
				</div>
			{:else}
				<EmptyState
					icon={Film}
					title="No movies chosen yet"
					message="Add the features this programme will show."
				>
					{#snippet action()}
						{@render addButtons('primary')}
						<Button href="{base}/library">Browse the library</Button>
					{/snippet}
				</EmptyState>
			{/if}

			{#if features.length}
				<div class="mt-3 flex flex-wrap items-center gap-2">{@render addButtons()}</div>
			{/if}
		</section>
	{:else if step === 'template'}
		<section class="mt-6">
			{@render heading(
				'The template',
				`Its running order is what your ${movieCount(features.length)} ${features.length === 1 ? 'is' : 'are'} built into`
			)}

			{#if templates.loading}
				<Spinner label="Loading templates…" size="sm" />
			{:else if templates.error}
				<ErrorState error={templates.error} retry={() => void templates.load()} compact />
			{:else if !allTemplates.length}
				<p class="mt-3 text-sm text-muted">
					No templates yet - a template defines the running order a programme is built from.
					<a class="text-accent hover:underline" href="{base}/templates/new"> Create a template </a>
				</p>
			{:else}
				{#if fittingTemplates.length}
					<p class="mt-3 text-sm text-muted">
						{fittingTemplates.length === 1
							? 'One template takes'
							: `${fittingTemplates.length} templates take`}
						exactly {movieCount(features.length)}.
					</p>
					<div class="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
						{#each fittingTemplates as template (template.id)}
							<TemplateCard
								{template}
								selected={selectedTemplateId === template.id}
								onselect={() => selectTemplate(template.id)}
							/>
						{/each}
					</div>
				{:else}
					<div class="mt-3 border border-warning/40 bg-warning/10 px-3 py-2.5 text-sm">
						<p class="flex items-start gap-2">
							<TriangleAlert size={15} class="mt-0.5 shrink-0 text-warning" />
							<span>
								<strong>No template takes {movieCount(features.length)}.</strong>
								A programme is built from a template's running order, so the number of features has to
								match exactly - either change the movies, or make a template with
								{features.length}
								{features.length === 1 ? 'feature' : 'features'}.
							</span>
						</p>
						<div class="mt-2.5 flex flex-wrap gap-2">
							<Button onclick={() => (step = 'films')}>
								<ArrowLeft size={14} /> Change the movies
							</Button>
							<Button href="{base}/templates/new">
								<LayoutTemplate size={14} /> Create a template
							</Button>
						</div>
					</div>
				{/if}

				{#if otherTemplates.length}
					<button
						type="button"
						class="mt-4 inline-flex items-center gap-1 text-xs text-muted transition-colors
							hover:text-text"
						aria-expanded={showAllTemplates}
						onclick={() => (showAllTemplates = !showAllTemplates)}
					>
						<ChevronDown
							size={12}
							class="transition-transform {showAllTemplates ? 'rotate-180' : ''}"
						/>
						{showAllTemplates ? 'Hide' : 'Show'} the other {otherTemplates.length}
						{otherTemplates.length === 1 ? 'template' : 'templates'}
					</button>
					{#if showAllTemplates}
						<div class="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
							{#each otherTemplates as template (template.id)}
								<TemplateCard
									{template}
									selected={false}
									disabled
									note={templateNote(template.number_of_features)}
									onselect={() => {}}
								/>
							{/each}
						</div>
					{/if}
				{/if}
			{/if}

			<p class="mt-4 border-t border-border pt-4 text-sm text-muted">
				None of these fit?
				<button type="button" class="text-accent hover:underline" onclick={startFromBlank}>
					Lay the running order out by hand
				</button>
				- your {movieCount(features.length)} come with you.
			</p>
		</section>
	{:else}
		<section class="mt-6">
			{@render heading('The programme', 'Name it, then create it')}

			<div class="mt-3 border border-border bg-surface-1 p-4">
				<div class="flex flex-col gap-3 sm:flex-row">
					<label class="flex min-w-0 flex-1 flex-col gap-1 text-sm" for="cp-name">
						<span class="font-medium">Name</span>
						<Input
							id="cp-name"
							placeholder={autoName || 'Programme name'}
							bind:value={name}
							oninput={() => (nameEdited = true)}
						/>
					</label>
					<label class="flex min-w-0 flex-1 flex-col gap-1 text-sm" for="cp-description">
						<span class="font-medium">Description</span>
						<Input
							id="cp-description"
							placeholder={autoDescription || 'Optional'}
							bind:value={description}
							oninput={() => (descEdited = true)}
						/>
					</label>
				</div>

				<div class="mt-4 flex flex-wrap items-center gap-x-4 gap-y-3 border-t border-border pt-3.5">
					<div class="min-w-0 text-sm" aria-live="polite">
						{#if previewFailed}
							<p class="flex items-center gap-1.5 text-warning">
								<TriangleAlert size={13} />
								Couldn't work out the running order - change the template or movies to try again.
							</p>
						{:else if preview}
							<p class="flex flex-wrap items-center gap-x-3 gap-y-1">
								<span class="font-mono text-muted">
									{itemCount} items · {estimated ? '≈ ' : ''}{formatRuntime(preview.total_runtime)}
								</span>
								{#if warnings.length}
									<button
										type="button"
										class="inline-flex items-center gap-1 rounded-sm text-xs text-warning
											hover:underline"
										aria-expanded={warningsOpen}
										onclick={() => (warningsOpen = !warningsOpen)}
									>
										<TriangleAlert size={12} />
										{warnings.length} warning{warnings.length !== 1 ? 's' : ''}
										<ChevronDown
											size={12}
											class="transition-transform {warningsOpen ? 'rotate-180' : ''}"
										/>
									</button>
								{/if}
							</p>
						{:else if ready}
							<Spinner label="Working out the running order…" size="sm" />
						{/if}
					</div>

					<div class="ml-auto flex items-center gap-2">
						<Button onclick={() => (step = 'template')}>
							<ArrowLeft size={14} /> Template
						</Button>
						<Button
							variant="primary"
							disabled={!canCreate || creating}
							onclick={() => void createProgramme()}
						>
							<ListVideo size={14} />
							{creating ? 'Creating…' : 'Create programme'}
						</Button>
					</div>
				</div>

				{#if warnings.length && warningsOpen}
					<ul
						class="mt-3 list-inside list-disc space-y-0.5 border-t border-border pt-3 text-xs text-muted"
					>
						{#each warnings as warning (warning)}
							<li>{warning}</li>
						{/each}
					</ul>
				{/if}
			</div>
		</section>

		<section class="mt-8">
			{@render heading(
				'Running order',
				`${selectedTemplate?.name ?? ''}${slotCount ? ` · ${slotCount === 1 ? '1 feature slot' : `${slotCount} feature slots`}` : ''}`
			)}
			{#if detailQuery.loading}
				<Spinner label="Laying out the running order…" size="sm" />
			{:else if detailQuery.error}
				<ErrorState
					message="Could not load the template's running order."
					retry={() => selectedTemplateId && selectTemplate(selectedTemplateId)}
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
									onchoose={() => void swapFilm(row.slotIndex)}
									onrandom={() => editRandom(row.slotIndex)}
									ontracks={() => openTracks(row.slotIndex)}
									onmove={(dir) => moveFeature(row.slotIndex, dir)}
								/>
							{:else}
								<SupportRow {row} />
							{/if}
						</li>
					{/each}
				</ol>
			{/if}
		</section>
	{/if}

	{#if step !== 'rundown'}
		<div
			class="sticky bottom-0 z-[5] mt-8 -mx-4 -mb-4 border-t border-border bg-bg px-4 py-3
				md:-mx-6 md:-mb-6 md:px-6"
		>
			{#if step === 'films'}
				<div class="flex flex-wrap items-center gap-x-4 gap-y-2">
					<p class="text-sm text-muted">
						{#if features.length}
							<span class="font-mono">
								{movieCount(features.length)}{featuresRuntime
									? ` · ${anyEstimatedFeature ? '≈ ' : ''}${formatRuntime(featuresRuntime)}`
									: ''}
							</span>
							<span class="text-faint">- trailers and idents come from the template</span>
						{:else}
							<span class="text-faint">Add at least one movie to continue</span>
						{/if}
					</p>
					<Button
						class="ml-auto"
						variant="primary"
						disabled={!features.length}
						onclick={() => (step = 'template')}
					>
						Choose a template <ArrowRight size={14} />
					</Button>
				</div>
			{:else if step === 'template'}
				<div class="flex flex-wrap items-center gap-x-4 gap-y-2">
					<Button onclick={() => (step = 'films')}>
						<ArrowLeft size={14} /> Back to the movies
					</Button>
					<p class="text-sm text-faint">
						{fittingTemplates.length
							? 'Pick a template to lay out the running order.'
							: 'No template takes this many features yet.'}
					</p>
				</div>
			{/if}
		</div>
	{/if}
{/if}

<Dialog bind:open={tracksOpen} title="Tracks - {tracksFilm ? tracksFilm.title : ''}">
	{#if tracksFilm}
		<TrackRadios
			name="cp"
			audioTracks={tracksFilm.audio_tracks}
			subtitleTracks={tracksFilm.subtitle_tracks}
			bind:audio={draftAudio}
			bind:subtitle={draftSubtitle}
		/>
	{/if}
	{#snippet footer()}
		<Button onclick={() => (tracksOpen = false)}>Cancel</Button>
		<Button variant="primary" onclick={applyTracks}>Done</Button>
	{/snippet}
</Dialog>

<Dialog bind:open={createdOpen} title="Programme created">
	<p class="text-sm text-muted">{createdSummary}</p>
	{#snippet footer()}
		<Button href="{base}/schedules?new={created?.id}">
			<CalendarPlus size={14} /> Schedule
		</Button>
		<Button disabled={cueing} onclick={() => void cueCreated()}>
			<Upload size={14} />
			{cueing ? 'Cueing…' : 'Cue for playout'}
		</Button>
		<Button variant="primary" onclick={() => void goto(`${base}/programmes/${created?.id}`)}>
			<Eye size={14} /> View programme
		</Button>
	{/snippet}
</Dialog>

<RandomPickDialog bind:open={randomOpen} initial={randomInitial} onconfirm={applyRandom} />

<PickerDialog kind="movie" bind:this={moviePicker} />
<PickerDialog
	kind="movie"
	mode="multi"
	bind:this={addPicker}
	isSelected={(picked) => features.some((it) => it.kind === 'movie' && it.id === picked.id)}
	onadd={(picked) => addFilm(picked.id)}
/>
