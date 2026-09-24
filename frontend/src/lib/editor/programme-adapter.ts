import type { BlockContent, EditorBlock, EditorContext, PaletteEntry } from './types';
import { HELP, commandSummary, filterDescription } from './types';

export const PROGRAMME_PALETTE: PaletteEntry[] = [
	{ type: 'movie', desc: 'Pick a movie' },
	{ type: 'trailer_rule', desc: 'Auto-select trailers', help: HELP.trailer_rule },
	{ type: 'trailer', desc: 'A specific trailer' },
	{ type: 'bumper', desc: 'A clip or a random pick from a tag' },
	{ type: 'audio_bumper', desc: 'Intro matching a feature’s audio format' },
	{ type: 'command', desc: 'A system action' },
	{ type: 'random_movie', desc: 'Pick from filters' },
	{ type: 'certification', desc: 'Rating card' }
];

export function defaultProgrammeContent(type: string): BlockContent {
	switch (type) {
		case 'movie':
			return {
				movie_id: null,
				title: null,
				audio_track: null,
				subtitle_track: null,
				credits_command_id: null
			};
		case 'bumper':
			// A specific clip (bumper_id) OR a random pick from a tag (tag_id + count); a tag = random.
			return { bumper_id: null, title: null, tag_id: null, tag_name: null, count: 1 };
		case 'trailer':
			return { trailer_id: null, title: null };
		case 'trailer_rule':
			return {
				reference_movie_id: null,
				count: 3,
				genre_ids: [],
				certificate_ceiling: '',
				year_from: null,
				year_to: null,
				trailer_tag_id: null
			};
		case 'command':
			return { command_id: null, name: null, hold_black: false };
		case 'random_movie':
			return {
				genre_ids: [],
				genre_names: [],
				certification: null,
				year_from: null,
				year_to: null,
				runtime_from: null,
				runtime_to: null,
				count: 1
			};
		case 'certification':
			return { reference_movie_id: null };
		case 'audio_bumper':
			return { reference_movie_id: null, bumper_id: null, bumper_title: null };
		default:
			return {};
	}
}

export interface ProgrammeItemIn {
	id: number;
	order: number;
	type: string;
	title: string;
	runtime: number;
	details: Record<string, unknown>;
}

export function programmeItemsToBlocks(items: ProgrammeItemIn[], uid: () => string): EditorBlock[] {
	return items.map((item, index) => {
		const d = item.details as BlockContent & Record<string, unknown>;
		let content: BlockContent;
		switch (item.type) {
			case 'movie':
				content = {
					movie_id: (d.movie_id as number | null) ?? null,
					title: item.title || 'Movie',
					audio_track: (d.audio_track as number | null) ?? null,
					subtitle_track: (d.subtitle_track as number | null) ?? null,
					credits_command_id: (d.credits_command_id as number | null) ?? null
				};
				break;
			case 'trailer_rule':
				content = {
					reference_movie_id: d.reference_movie_id ?? null,
					bound_to_block_order: d.bound_to_block_order ?? null,
					rule_id: d.rule_id ?? null,
					count: d.count || 3,
					genre_ids: (d.genre_ids as number[] | undefined) ?? [],
					certificate_ceiling: (d.certificate_ceiling as string | undefined) ?? '',
					year_from: (d.year_from as number | null | undefined) ?? null,
					year_to: (d.year_to as number | null | undefined) ?? null,
					trailer_tag_id: d.trailer_tag_id ?? null
				};
				break;
			case 'command':
				content = {
					command_id: d.command_id ?? null,
					name: item.title || 'Command',
					hold_black: d.hold_black ?? false
				};
				break;
			// The retired `random_bumper` type loads as a tag-carrying bumper.
			case 'bumper':
			case 'random_bumper':
				content = {
					bumper_id: d.bumper_id ?? null,
					title: item.title || 'User media',
					tag_id: d.tag_id ?? null,
					tag_name: (d.tag_name as string | null) ?? null,
					count: d.count || 1
				};
				break;
			case 'trailer':
				content = { trailer_id: d.trailer_id ?? null, title: item.title || 'Trailer' };
				break;
			case 'random_movie':
				content = {
					genre_ids: d.genre_ids ?? [],
					genre_names: d.genre_names ?? [],
					certification: d.certification ?? null,
					year_from: d.year_from ?? null,
					year_to: d.year_to ?? null,
					runtime_from: d.runtime_from ?? null,
					runtime_to: d.runtime_to ?? null,
					count: d.count || 1
				};
				break;
			case 'certification':
				content = { reference_movie_id: d.reference_movie_id ?? null };
				break;
			case 'audio_bumper':
				content = {
					reference_movie_id: d.reference_movie_id ?? null,
					bumper_id: d.bumper_id ?? null,
					bumper_title: (d.bumper_title as string | null) ?? null
				};
				break;
			default:
				content = { ...(d as BlockContent) };
		}
		return {
			uid: uid(),
			// Normalise the retired `random_bumper` to `bumper`.
			type: item.type === 'random_bumper' ? 'bumper' : item.type,
			order: item.order ?? index,
			content,
			details: {
				year: (d.year as number | null) ?? null,
				certification: (d.certification as string | null) ?? null,
				thumbnail_url: (d.thumbnail_url as string | null) ?? null,
				duration: (d.duration as number | null) ?? null,
				matching_movies: (d.matching_count as number | null) ?? null
			}
		};
	});
}

export function programmeBlockError(block: EditorBlock): string | null {
	switch (block.type) {
		case 'movie':
			return block.content.movie_id ? null : 'Choose a movie';
		case 'trailer':
			return block.content.trailer_id ? null : 'Choose a trailer';
		case 'bumper':
			if (block.content.tag_id) return null;
			return block.content.bumper_id ? null : 'Choose a clip or a tag';
		case 'command':
			return block.content.command_id ? null : 'Choose a command';
		case 'certification':
			return block.content.reference_movie_id ? null : 'Choose a movie';
		case 'audio_bumper':
			if (block.content.bumper_id || block.content.reference_movie_id) return null;
			return 'Choose which feature';
		case 'trailer_rule':
			// Always valid: reference movie optional, empty criteria picks any trailers.
			return null;
		default:
			return null;
	}
}

export function programmeBlockTitle(block: EditorBlock): string {
	const c = block.content;
	switch (block.type) {
		case 'movie':
			return c.title || 'Movie';
		case 'trailer_rule':
			return `${c.count || 3} Trailers`;
		case 'command':
			return c.name || 'Command';
		case 'bumper':
			if (c.tag_id) return `Random user media${(c.count ?? 1) > 1 ? ` (${c.count}x)` : ''}`;
			return c.title || 'User media';
		case 'trailer':
			return c.title || 'Trailer';
		case 'random_movie': {
			const filters = filterDescription(c);
			return `Random Movie${filters ? ` (${filters})` : ''}`;
		}
		case 'certification':
			return 'Certification';
		case 'audio_bumper':
			return 'Audio user media';
		default:
			return 'Unknown block';
	}
}

export function programmeBlockSummary(block: EditorBlock, ctx: EditorContext): string {
	const c = block.content;
	const d = block.details;
	switch (block.type) {
		case 'movie': {
			const runtime = d.runtime ? `${Math.floor(d.runtime / 60)}h ${d.runtime % 60}m` : '';
			const year = d.year ? ` · ${d.year}` : '';
			const rating = d.certification ? ` · ${d.certification}` : '';
			return `${runtime}${year}${rating}` || 'Feature';
		}
		case 'trailer_rule': {
			if (c.bound_to_block_order != null) {
				const boundTag = ctx.trailerTags.find((t) => t.id === c.trailer_tag_id);
				return 'For random movie' + (boundTag ? ` · Tag: ${boundTag.name}` : '');
			}
			const parts: string[] = [];
			const genres = (c.genre_ids ?? [])
				.map((id) => ctx.genres.find((g) => g.id === id)?.name)
				.filter(Boolean);
			if (genres.length) parts.push(genres.join(' + '));
			if (c.certificate_ceiling) parts.push(`≤ ${c.certificate_ceiling}`);
			if (c.year_from || c.year_to) parts.push(`${c.year_from ?? '…'}-${c.year_to ?? '…'}`);
			const tag = ctx.trailerTags.find((t) => t.id === c.trailer_tag_id);
			if (tag) parts.push(`Tag: ${tag.name}`);
			const ref = c.reference_movie_id
				? ctx.movies.find((m) => m.id === c.reference_movie_id)
				: null;
			const refInfo = ref ? `Like ${ref.title}` : '';
			const crit = parts.join(' · ');
			return [refInfo, crit].filter(Boolean).join(' · ') || 'Any trailers';
		}
		case 'command': {
			const cmd = ctx.commands.find((x) => x.id === c.command_id);
			return commandSummary(cmd, !!c.hold_black);
		}
		case 'bumper':
			if (c.tag_id) {
				const tag = ctx.tags.find((t) => t.id === c.tag_id);
				return tag ? `Random from ${tag.name} tag` : 'Random selection from tag';
			}
			return d.duration ? formatSeconds(d.duration) : 'Media content';
		case 'trailer': {
			const parts: string[] = [];
			if (d.year) parts.push(String(d.year));
			if (d.duration) parts.push(formatSeconds(d.duration));
			return parts.join(' · ') || 'Specific trailer';
		}
		case 'random_movie':
			return d.matching_movies
				? `${d.matching_movies} movies match filters`
				: 'Random selection from library';
		case 'certification':
			return 'Rating card for movie';
		case 'audio_bumper': {
			if (c.bumper_id) return `Plays “${c.bumper_title || 'user media'}”`;
			if (c.reference_movie_id) {
				const idx = ctx.programmeMovies.findIndex((m) => m.id === c.reference_movie_id);
				const ref =
					ctx.programmeMovies[idx] ?? ctx.movies.find((m) => m.id === c.reference_movie_id);
				const label = idx >= 0 ? `Feature ${idx + 1}` : ref?.title;
				return ref
					? `Auto-picks the intro matching ${label} (${ref.title})`
					: 'Auto-picks the intro for the chosen feature';
			}
			return 'Choose which feature this intro matches';
		}
		default:
			return 'Programme content';
	}
}

function formatSeconds(seconds: number): string {
	const total = Math.round(seconds);
	const h = Math.floor(total / 3600);
	const m = Math.floor((total % 3600) / 60);
	const s = total % 60;
	if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
	return `${m}:${String(s).padStart(2, '0')}`;
}

// Field names match ProgrammeService.process_programme_item; random_movie sends `genre_ids` (not `genre_id`).
export function blocksToProgrammeItems(blocks: EditorBlock[]): Record<string, unknown>[] {
	return blocks.map((block) => {
		const c = block.content;
		const item: Record<string, unknown> = { type: block.type, order: block.order };
		switch (block.type) {
			case 'movie':
				item.movie_id = c.movie_id;
				item.audio_track_index = c.audio_track;
				item.subtitle_track_index = c.subtitle_track;
				item.credits_command_id = c.credits_command_id;
				break;
			case 'trailer':
				item.trailer_id = c.trailer_id;
				break;
			case 'bumper':
				// A tag means random (send tag + count); else a specific clip.
				if (c.tag_id) {
					item.tag_id = c.tag_id;
					item.tag_name = c.tag_name;
					item.count = c.count ?? 1;
				} else {
					item.bumper_id = c.bumper_id;
				}
				break;
			case 'random_movie':
				item.genre_ids = c.genre_ids ?? [];
				item.certification = c.certification;
				item.year_from = c.year_from;
				item.year_to = c.year_to;
				item.runtime_from = c.runtime_from;
				item.runtime_to = c.runtime_to;
				item.count = c.count || 1;
				break;
			case 'command':
				item.command_id = c.command_id;
				item.hold_black = !!c.hold_black;
				break;
			case 'trailer_rule':
				item.reference_movie_id = c.reference_movie_id || null;
				item.bound_to_block_order = c.bound_to_block_order ?? null;
				item.count = c.count;
				item.genre_ids = c.genre_ids ?? [];
				item.certificate_ceiling = c.certificate_ceiling || '';
				item.year_from = c.year_from ?? null;
				item.year_to = c.year_to ?? null;
				item.trailer_tag_id = c.trailer_tag_id || null;
				break;
			case 'certification':
				// The API expects movie_id here, not reference_movie_id.
				item.movie_id = c.reference_movie_id;
				break;
			case 'audio_bumper':
				item.reference_movie_id = c.reference_movie_id || null;
				item.bumper_id = c.bumper_id || null;
				break;
		}
		return item;
	});
}

export function referencedMovieIds(blocks: EditorBlock[]): number[] {
	const ids = new Set<number>();
	for (const block of blocks) {
		if (block.type === 'movie' && block.content.movie_id) ids.add(block.content.movie_id);
		if (
			(block.type === 'trailer_rule' ||
				block.type === 'certification' ||
				block.type === 'audio_bumper') &&
			block.content.reference_movie_id
		)
			ids.add(block.content.reference_movie_id);
	}
	return [...ids];
}
