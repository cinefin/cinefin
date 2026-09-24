import { api, unwrap } from '$lib/api/client';
import type { EditorBlock, EditorContext } from './types';

type Commit = (mutate: () => void) => void;

export async function pickMovieIntoBlock(
	block: EditorBlock,
	ctx: EditorContext,
	commit: Commit
): Promise<void> {
	const picked = await ctx.pickMovie?.();
	if (!picked) return;
	let detail: Awaited<ReturnType<typeof fetchMovieDetail>> | null = null;
	try {
		detail = await fetchMovieDetail(picked.id);
	} catch (e) {
		console.error('Failed to fetch movie details:', e);
	}
	commit(() => {
		block.content.movie_id = picked.id;
		block.content.title = picked.title;
		block.content.audio_track = null;
		block.content.subtitle_track = null;
		block.details = {
			runtime: detail?.runtime ?? picked.runtime ?? null,
			year: detail?.year ?? picked.year ?? null,
			certification: detail?.certification ?? picked.certification ?? null,
			thumbnail_url: detail?.thumbnail_url ?? picked.thumbnail_url ?? null,
			audio_tracks: detail?.audio_tracks ?? [],
			subtitle_tracks: detail?.subtitle_tracks ?? []
		};
	});
	// Keep the reference-movie selects offering this film too.
	if (!ctx.movies.some((m) => m.id === picked.id)) {
		ctx.movies.push({ id: picked.id, title: picked.title });
		ctx.movies.sort((a, b) => a.title.localeCompare(b.title));
	}
}

export async function fetchMovieDetail(movieId: number) {
	return await unwrap(
		api.GET('/api/v2/movies/{movie_id}', { params: { path: { movie_id: movieId } } })
	);
}

export async function pickBumperIntoBlock(
	block: EditorBlock,
	ctx: EditorContext,
	commit: Commit
): Promise<void> {
	const picked = await ctx.pickBumper();
	if (!picked) return;
	commit(() => {
		block.content.bumper_id = picked.id;
		block.content.title = picked.title;
		block.details = { ...block.details, duration: picked.duration ?? null };
	});
}

export async function pickTrailerIntoBlock(
	block: EditorBlock,
	ctx: EditorContext,
	commit: Commit
): Promise<void> {
	const picked = await ctx.pickTrailer();
	if (!picked) return;
	commit(() => {
		block.content.trailer_id = picked.id;
		block.content.title = picked.title;
		block.details = {
			...block.details,
			year: picked.year ?? null,
			duration: picked.duration ?? null,
			content_rating: picked.content_rating ?? null
		};
	});
}
