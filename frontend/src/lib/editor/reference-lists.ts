import { api, unwrap } from '$lib/api/client';
import type { EditorContext } from './types';

/** Fill the editor's reference lists; each degrades quietly (the blocks are what must be right). */
export async function loadReferenceLists(ctx: EditorContext): Promise<void> {
	const use = <T>(what: string, pending: Promise<T>, apply: (v: T) => void) =>
		pending.then(apply, (e) => console.error(`${what} not available:`, e));
	const programme = ctx.mode === 'programme';
	await Promise.all([
		programme &&
			use(
				'Movies',
				unwrap(
					api.GET('/api/v2/movies/list', {
						params: { query: { per_page: 100, sort: 'title', order: 'asc' } }
					})
				),
				(v) => (ctx.movies = v.items.map((m) => ({ id: m.id, title: m.title })))
			),
		use('Commands', unwrap(api.GET('/api/v2/commands/list')), (v) => (ctx.commands = v.commands)),
		use(
			'Tags',
			unwrap(api.GET('/api/v2/media/tags', { params: { query: { per_page: 100 } } })),
			(v) => (ctx.tags = v.tags)
		),
		use('Trailer tags', unwrap(api.GET('/api/v2/trailers/tags')), (v) => {
			ctx.trailerTags = (v as unknown as { tags: { id: number; name: string }[] }).tags;
		}),
		programme && use('Genres', unwrap(api.GET('/api/v2/movies/genres')), (v) => (ctx.genres = v)),
		// Certificate options follow the active ratings scheme (BBFC/MPAA), in order.
		use(
			'Ratings options',
			unwrap(api.GET('/api/v2/movies/ratings-options')),
			(v) => (ctx.certifications = v.ratings ?? [])
		)
	]);
}
