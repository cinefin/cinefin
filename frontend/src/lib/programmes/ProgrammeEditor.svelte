<script lang="ts">
	// The programme editing surface — the running order, built block by block.
	// Mounted by the programme page at ?edit=1 (existing) and /programmes/new
	// (virtual id). Reference lists load when THIS component mounts, so viewing
	// never pays for the editor.
	import type { Snippet } from 'svelte';
	import { base } from '$app/paths';
	import { beforeNavigate } from '$app/navigation';
	import { page } from '$app/state';
	import { api, toApiError, unwrap } from '$lib/api/client';
	import { showToast } from '$lib/toast.svelte';
	import { invalidate } from '$lib/invalidate';
	import { Eraser, ListVideo, Plus, Save } from '@lucide/svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import BlockList from '$lib/editor/BlockList.svelte';
	import BlockPalette from '$lib/editor/BlockPalette.svelte';
	import PickerDialog from '$lib/editor/PickerDialog.svelte';
	import ShortcutsDialog from '$lib/editor/ShortcutsDialog.svelte';
	import { BlockEditor } from '$lib/editor/editor.svelte';
	import {
		pickMovieIntoBlock,
		pickTrailerIntoBlock,
		fetchMovieDetail
	} from '$lib/editor/pick-actions';
	import {
		PROGRAMME_PALETTE,
		blocksToProgrammeItems,
		defaultProgrammeContent,
		programmeBlockError,
		programmeItemsToBlocks,
		referencedMovieIds
	} from '$lib/editor/programme-adapter';
	import type { EditorContext, MovieOption } from '$lib/editor/types';
	import { ApiError } from '$lib/api/client';

	type ApiItems = Parameters<typeof programmeItemsToBlocks>[0];

	interface Props {
		/** null = a programme that does not exist yet (save POSTs it). */
		programmeId: number | null;
		items?: ApiItems;
		initialName?: string;
		initialDescription?: string;
		/** Mirrors the editor's unsaved state out, for the host's own guards. */
		dirty?: boolean;
		onsaved?: (programmeId: number, playlistStale: boolean) => void;
		/** Host actions for the toolbar's right-hand end (Done, Back, …). */
		actions?: Snippet;
	}

	let {
		programmeId,
		items = [],
		initialName = '',
		initialDescription = '',
		dirty = $bindable(false),
		onsaved,
		actions
	}: Props = $props();

	// svelte-ignore state_referenced_locally
	let name = $state(initialName);
	// svelte-ignore state_referenced_locally
	let description = $state(initialDescription);
	// A created programme keeps being edited in place, so PUT to this id.
	// svelte-ignore state_referenced_locally
	let savedId = $state<number | null>(programmeId);

	const editor = new BlockEditor<{ name: string; description: string }>({
		captureMeta: () => ({ name, description }),
		restoreMeta: (meta) => {
			name = meta.name;
			description = meta.description;
		}
	});

	$effect(() => {
		dirty = editor.dirty;
	});

	let moviePicker = $state<PickerDialog>();
	let bumperPicker = $state<PickerDialog>();
	let trailerPicker = $state<PickerDialog>();
	const ctx: EditorContext = $state({
		mode: 'programme',
		movies: [],
		programmeMovies: [],
		commands: [],
		tags: [],
		trailerTags: [],
		genres: [],
		certifications: [],
		featureCount: 0,
		pickMovie: () => moviePicker!.pick(),
		pickBumper: () => bumperPicker!.pick(),
		pickTrailer: () => trailerPicker!.pick()
	});

	// Films in rundown order (what the certification select offers), derived from
	// the blocks so edits reflect at once; the same film twice is one choice.
	const programmeMovies = $derived.by(() => {
		const seen = new Set<number>();
		const out: MovieOption[] = [];
		for (const block of editor.blocks) {
			if (block.type !== 'movie') continue;
			const id = block.content.movie_id;
			if (!id || seen.has(id)) continue;
			seen.add(id);
			out.push({ id, title: block.content.title || 'Movie' });
		}
		return out;
	});
	$effect(() => {
		ctx.programmeMovies = programmeMovies;
	});

	let loading = $state(true);
	let loadError = $state<ApiError | null>(null);
	let booted = false;

	$effect(() => {
		if (booted) return;
		booted = true;
		void init();
	});

	async function init(): Promise<void> {
		loading = true;
		loadError = null;
		try {
			// Reference lists degrade quietly; the blocks are what must be right.
			await loadReferenceLists();
			await buildBlocks();
		} catch (e) {
			loadError = toApiError(e);
		} finally {
			loading = false;
		}
	}

	async function loadReferenceLists(): Promise<void> {
		const [movies, commands, tags, trailerTags, genres] = await Promise.allSettled([
			unwrap(
				api.GET('/api/v2/movies/list', {
					params: { query: { per_page: 100, sort: 'title', order: 'asc' } }
				})
			),
			unwrap(api.GET('/api/v2/commands/list')),
			unwrap(api.GET('/api/v2/media/tags', { params: { query: { per_page: 100 } } })),
			unwrap(api.GET('/api/v2/trailers/tags')),
			unwrap(api.GET('/api/v2/movies/genres'))
		]);
		if (movies.status === 'fulfilled') {
			ctx.movies = movies.value.items.map((m) => ({ id: m.id, title: m.title }));
			ctx.certifications = movies.value.filters.certifications;
		} else console.error('Movies not available:', movies.reason);
		if (commands.status === 'fulfilled') ctx.commands = commands.value.commands;
		else console.error('Commands not available:', commands.reason);
		if (tags.status === 'fulfilled') ctx.tags = tags.value.tags;
		else console.error('Tags not available:', tags.reason);
		if (trailerTags.status === 'fulfilled')
			ctx.trailerTags = (
				trailerTags.value as unknown as { tags: { id: number; name: string }[] }
			).tags;
		else console.error('Trailer tags not available:', trailerTags.reason);
		if (genres.status === 'fulfilled') ctx.genres = genres.value;
		else console.error('Genres not available:', genres.reason);
	}

	// Turn the host's items into blocks, filling each movie block's track lists
	// and making sure every referenced movie appears in the reference selects.
	async function buildBlocks(): Promise<void> {
		if (!items.length) {
			editor.reset([]);
			applyRandomMovieUrlParams();
			return;
		}
		const blocks = programmeItemsToBlocks(items, () => editor.uid());
		await Promise.all(
			referencedMovieIds(blocks).map(async (movieId) => {
				try {
					const movie = await fetchMovieDetail(movieId);
					for (const block of blocks) {
						if (block.type === 'movie' && block.content.movie_id === movieId) {
							block.details = {
								runtime: movie.runtime,
								year: movie.year,
								certification: movie.certification,
								thumbnail_url: movie.thumbnail_url,
								audio_tracks: movie.audio_tracks,
								subtitle_tracks: movie.subtitle_tracks
							};
						}
					}
					if (!ctx.movies.some((m) => m.id === movie.id)) {
						ctx.movies.push({ id: movie.id, title: movie.title });
						ctx.movies.sort((a, b) => a.title.localeCompare(b.title));
					}
				} catch (e) {
					console.error(`Failed to load details for movie ${movieId}:`, e);
				}
			})
		);
		editor.reset(blocks);
	}

	/** Legacy deep link from the library: ?random_movie=true&rm_… adds a block. */
	function applyRandomMovieUrlParams(): void {
		const params = page.url.searchParams;
		if (params.get('random_movie') !== 'true') return;
		const genreId = params.get('rm_genre_id');
		const genreName = params.get('rm_genre_name');
		editor.add('random_movie', {
			...defaultProgrammeContent('random_movie'),
			genre_ids: genreId ? [parseInt(genreId, 10)] : [],
			genre_names: genreName ? [genreName] : [],
			certification: params.get('rm_certification') || null,
			year_from: params.get('rm_year_from') ? parseInt(params.get('rm_year_from')!, 10) : null,
			year_to: params.get('rm_year_to') ? parseInt(params.get('rm_year_to')!, 10) : null,
			count: 1
		});
	}

	async function addBlock(type: string): Promise<void> {
		const block = editor.add(type, defaultProgrammeContent(type));
		scrollToBlock(editor.blocks.length - 1);
		// Movie/trailer blocks go straight to their picker; cancelling keeps the block.
		if (type === 'movie') await pickMovieIntoBlock(block, ctx, (m) => runPicked(m));
		else if (type === 'trailer') await pickTrailerIntoBlock(block, ctx, (m) => runPicked(m));
	}

	// The add already pushed an undo snapshot, so just mutate + mark dirty.
	function runPicked(mutate: () => void): void {
		mutate();
		editor.markDirty();
	}

	function scrollToBlock(index: number): void {
		setTimeout(() => {
			document
				.querySelector(`[data-block-index="${index}"]`)
				?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
		}, 50);
	}

	let confirmDialog = $state<ConfirmDialog>();

	async function removeBlock(index: number): Promise<void> {
		if (!(await confirmDialog!.confirm('Are you sure you want to delete this block?'))) return;
		editor.pushUndo();
		editor.removeAt(index);
		showToast('Block deleted - press Ctrl+Z to undo', 'info');
	}

	async function clearProgramme(): Promise<void> {
		if (!editor.blocks.length && !name && !description) return;
		if (
			!(await confirmDialog!.confirm('Clear the programme and start over?', {
				confirmLabel: 'Clear'
			}))
		)
			return;
		editor.pushUndo();
		name = '';
		description = '';
		editor.blocks = [];
		editor.showValidation = false;
		editor.markDirty();
		showToast('Programme cleared - press Ctrl+Z to undo', 'info');
	}

	let saving = $state(false);
	const canSave = $derived(!!name.trim() && editor.blocks.length > 0);

	// The host's own "discard?" dialog calls this before closing the editor, so
	// the navigation guard below doesn't ask the same question again.
	export function discardChanges(): void {
		editor.dirty = false;
	}

	export async function save(): Promise<void> {
		if (saving) return;
		if (!name.trim()) {
			showToast('Please enter a programme name', 'warning');
			return;
		}
		if (editor.blocks.length === 0) {
			showToast('Programme cannot be empty', 'warning');
			return;
		}

		const invalid = editor.blocks.filter((b) => programmeBlockError(b)).length;
		editor.showValidation = true;
		if (invalid > 0) {
			scrollToBlock(editor.blocks.findIndex((b) => programmeBlockError(b)));
			showToast(
				`${invalid} block${invalid > 1 ? 's need' : ' needs'} attention before saving`,
				'warning'
			);
			return;
		}

		const payload = {
			name: name.trim(),
			description: description.trim(),
			items: blocksToProgrammeItems(editor.blocks)
		};

		saving = true;
		try {
			if (savedId === null) {
				const data = await unwrap(
					api.POST('/api/v2/programmes/create', { body: { ...payload, preview: false } })
				);
				const created = data as unknown as { id?: number };
				editor.dirty = false;
				editor.showValidation = false;
				showToast('Programme created', 'success');
				if (created.id) {
					savedId = created.id;
					onsaved?.(created.id, false);
				}
			} else {
				const data = await unwrap(
					api.PUT('/api/v2/programmes/{programme_id}', {
						params: { path: { programme_id: savedId } },
						body: payload
					})
				);
				const stale = !!data.programme.playlist_stale;
				editor.dirty = false;
				editor.showValidation = false;
				showToast(
					stale
						? 'Programme saved, but the playlist could not be updated - use Regenerate to retry'
						: 'Programme saved',
					stale ? 'warning' : 'success'
				);
				onsaved?.(savedId, stale);
			}
			invalidate('programmes');
		} catch (e) {
			showToast(
				'Error saving programme: ' + (e instanceof Error ? e.message : 'Unknown error'),
				'error'
			);
		} finally {
			saving = false;
		}
	}

	const totalSeconds = $derived(
		editor.blocks.reduce((sum, b) => {
			if (b.details.runtime) return sum + b.details.runtime * 60;
			if (b.details.duration) return sum + b.details.duration;
			return sum;
		}, 0)
	);
	const statsText = $derived.by(() => {
		const h = Math.floor(totalSeconds / 3600);
		const m = Math.floor((totalSeconds % 3600) / 60);
		const blocks = editor.blocks.length;
		return `${blocks} ${blocks === 1 ? 'block' : 'blocks'} · ${h}h ${m}m`;
	});

	let shortcuts = $state<ShortcutsDialog>();

	function onKeydown(e: KeyboardEvent): void {
		editor.handleKeydown(e, {
			onSave: () => {
				if (!editor.dirty) {
					showToast('No unsaved changes', 'info');
					return;
				}
				void save();
			},
			onHelp: () => shortcuts?.toggle()
		});
	}

	function onBeforeUnload(e: BeforeUnloadEvent): void {
		if (editor.dirty) e.preventDefault();
	}

	// SPA navigations bypass beforeunload — guard them too.
	beforeNavigate((nav) => {
		if (editor.dirty && !window.confirm('You have unsaved changes. Leave without saving?')) {
			nav.cancel();
		}
	});
</script>

<svelte:window onkeydown={onKeydown} onbeforeunload={onBeforeUnload} />

{#if loading}
	<div class="p-4"><Spinner label="Loading the editor…" /></div>
{:else if loadError}
	<div class="p-4"><ErrorState error={loadError} retry={() => void init()} /></div>
{:else}
	<div class="space-y-4 p-4">
		<div class="flex flex-wrap items-end gap-3">
			<label class="flex min-w-48 flex-1 flex-col gap-1 text-sm" for="pe-name">
				<span class="text-xs text-muted">Name</span>
				<Input
					id="pe-name"
					placeholder="Programme name"
					bind:value={name}
					oninput={() => editor.markDirty()}
				/>
			</label>
			<label class="flex min-w-56 flex-[2] flex-col gap-1 text-sm" for="pe-description">
				<span class="text-xs text-muted">Description</span>
				<Input
					id="pe-description"
					placeholder="Optional"
					bind:value={description}
					oninput={() => editor.markDirty()}
				/>
			</label>
		</div>

		<div class="flex flex-wrap items-center gap-2 border-t border-border pt-3">
			<span class="font-mono text-xs text-muted">{statsText}</span>
			{#if editor.dirty}
				<span class="h-2 w-2 bg-warning" title="Unsaved changes"></span>
			{/if}
			<div class="ml-auto flex flex-wrap items-center gap-2">
				<Button size="sm" onclick={() => void clearProgramme()} title="Empty the running order">
					<Eraser size={13} /> Clear
				</Button>
				<Button
					size="sm"
					variant="primary"
					disabled={!canSave || saving}
					title="Save the programme (Ctrl+S)"
					onclick={() => void save()}
				>
					<Save size={13} />
					{saving ? 'Saving…' : 'Save'}
				</Button>
				{#if actions}{@render actions()}{/if}
			</div>
		</div>

		<div class="flex flex-col gap-4 md:flex-row md:items-start">
			<div class="min-w-0 flex-1">
				{#if editor.blocks.length === 0}
					<EmptyState
						icon={ListVideo}
						title="This running order is empty"
						message="Add blocks from the palette to build it, then drag to reorder. Prefer a guided start? Create from a template instead."
						compact
					>
						{#snippet action()}
							<Button href="{base}/programmes/create" size="sm">Create from a template</Button>
						{/snippet}
					</EmptyState>
				{:else}
					<BlockList {editor} {ctx} onremove={(i) => void removeBlock(i)} />
				{/if}
			</div>

			<aside class="md:sticky md:top-20 md:w-52 md:shrink-0">
				<p class="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-faint">
					<Plus size={12} /> Add block
				</p>
				<BlockPalette types={PROGRAMME_PALETTE} onadd={(type) => void addBlock(type)} />
			</aside>
		</div>
	</div>
{/if}

<PickerDialog kind="movie" bind:this={moviePicker} />
<PickerDialog kind="bumper" bind:this={bumperPicker} />
<PickerDialog kind="trailer" bind:this={trailerPicker} />
<ConfirmDialog bind:this={confirmDialog} title="Delete block?" confirmLabel="Delete" />
<ShortcutsDialog bind:this={shortcuts} />
