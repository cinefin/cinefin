<script lang="ts">
	// The running-order editor, mounted by the programme page at ?edit=1 and /programmes/new.
	// Reference lists load when it mounts, so viewing never pays for the editor.
	import { onMount, type Snippet } from 'svelte';
	import { base } from '$app/paths';
	import { page } from '$app/state';
	import { api, unwrap } from '$lib/api/client';
	import { showToast } from '$lib/toast.svelte';
	import { invalidate } from '$lib/invalidate';
	import { ListVideo } from '@lucide/svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import EditorShell from '$lib/editor/EditorShell.svelte';
	import { EditorSession } from '$lib/editor/session.svelte';
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
	import type { MovieOption } from '$lib/editor/types';

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
	const session = new EditorSession('programme', programmeId, initialName, initialDescription);
	const { editor, ctx } = session;

	$effect(() => {
		dirty = editor.dirty;
	});

	// Films in rundown order for the certification select; the same film twice is one choice.
	$effect(() => {
		const seen = new Set<number>();
		const out: MovieOption[] = [];
		for (const block of editor.blocks) {
			const id = block.type === 'movie' ? block.content.movie_id : null;
			if (!id || seen.has(id)) continue;
			seen.add(id);
			out.push({ id, title: block.content.title || 'Movie' });
		}
		ctx.programmeMovies = out;
	});

	onMount(() => void session.init(buildBlocks));

	// Fill each movie block's track lists and make sure every referenced movie is in the selects.
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
		editor.scrollTo(editor.blocks.length - 1);
		// Movie/trailer blocks go straight to their picker; cancelling keeps the block.
		if (type === 'movie') await pickMovieIntoBlock(block, ctx, session.picked);
		else if (type === 'trailer') await pickTrailerIntoBlock(block, ctx, session.picked);
	}

	// Called by the host's own discard dialog, so the navigation guard doesn't ask again.
	export function discardChanges(): void {
		editor.dirty = false;
	}

	export async function save(): Promise<void> {
		if (session.saving || !session.hasBasics()) return;
		if (!session.checkBlocks(programmeBlockError, 'block')) return;

		const payload = {
			name: session.name.trim(),
			description: session.description.trim(),
			items: blocksToProgrammeItems(editor.blocks)
		};

		await session.save(async () => {
			const savedId = session.savedId;
			if (savedId === null) {
				const data = await unwrap(
					api.POST('/api/v2/programmes/create', { body: { ...payload, preview: false } })
				);
				const created = data as unknown as { id?: number };
				session.clean();
				showToast('Programme created', 'success');
				if (created.id) {
					session.savedId = created.id;
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
				session.clean();
				showToast(
					stale
						? 'Programme saved, but the playlist could not be updated - use Regenerate to retry'
						: 'Programme saved',
					stale ? 'warning' : 'success'
				);
				onsaved?.(savedId, stale);
			}
			invalidate('programmes');
		});
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
</script>

<EditorShell
	{session}
	{actions}
	stats={statsText}
	palette={PROGRAMME_PALETTE}
	onadd={(type) => void addBlock(type)}
	onsave={() => void save()}
>
	{#snippet empty()}
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
	{/snippet}
</EditorShell>
