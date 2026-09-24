// Both editors edit an ordered list of `EditorBlock`s; per-context adapters
// (programme-adapter.ts / template-adapter.ts) translate to/from the two wire models.
import type { components } from '$lib/api/types.gen';

export type CommandInfo = components['schemas']['CommandSchema'];
export type AudioTrack = components['schemas']['AudioTrackSchema'];
export type SubtitleTrack = components['schemas']['SubtitleTrackSchema'];

export type EditorMode = 'programme' | 'template';

// Per-type config fields, one flat optional bag; the adapters normalise the two wire namings into these.
export interface BlockContent {
	movie_id?: number | null;
	title?: string | null;
	audio_track?: number | null;
	subtitle_track?: number | null;
	credits_command_id?: number | null;
	feature_number?: number | null;
	trailer_id?: number | null;
	bumper_id?: number | null;
	bumper_title?: string | null;
	command_id?: number | null;
	name?: string | null;
	hold_black?: boolean;
	// Trailer rule: programme mode uses hard criteria (genre_ids match ALL,
	// certificate_ceiling, year range) with an OPTIONAL reference movie that only
	// seeds + ranks; template mode keeps its own match_* toggles.
	reference_movie_id?: number | null;
	bound_to_block_order?: number | null;
	bound_to_feature?: number | null;
	rule_id?: number | null;
	count?: number;
	certificate_ceiling?: string;
	match_genres?: boolean;
	match_certification?: boolean;
	match_year?: boolean;
	year_delta?: number;
	trailer_tag_id?: number | null;
	certification_feature?: number | null;
	tag_id?: number | null;
	tag_name?: string | null;
	genre_ids?: number[];
	genre_names?: string[];
	certification?: string | null;
	year_from?: number | null;
	year_to?: number | null;
	runtime_from?: number | null;
	runtime_to?: number | null;
}

export interface BlockDetails {
	/** Movie runtime in MINUTES. */
	runtime?: number | null;
	/** Clip duration in SECONDS. */
	duration?: number | null;
	year?: number | null;
	certification?: string | null;
	content_rating?: string | null;
	thumbnail_url?: string | null;
	audio_tracks?: AudioTrack[];
	subtitle_tracks?: SubtitleTrack[];
	matching_movies?: number | null;
}

export interface EditorBlock {
	/** Local list key — never sent to the API. */
	uid: string;
	type: string;
	order: number;
	content: BlockContent;
	details: BlockDetails;
}

export interface Option {
	id: number;
	name: string;
}

export interface MovieOption {
	id: number;
	title: string;
}

export interface PickedItem {
	id: number;
	title: string;
	year?: number | null;
	/** Movie runtime in minutes. */
	runtime?: number | null;
	/** Clip duration in seconds. */
	duration?: number | null;
	certification?: string | null;
	content_rating?: string | null;
	director?: string | null;
	thumbnail_url?: string | null;
	screenshot_url?: string | null;
}

export interface EditorContext {
	mode: EditorMode;
	/** Programme mode: movies offered by the reference-movie selects. */
	movies: MovieOption[];
	// Programme mode: films actually in this programme, in rundown order, deduped —
	// the certification select offers these (a rating card is only for a film shown).
	programmeMovies: MovieOption[];
	commands: CommandInfo[];
	tags: Option[];
	trailerTags: Option[];
	genres: Option[];
	certifications: string[];
	featureCount: number;
	pickMovie?: () => Promise<PickedItem | null>;
	pickBumper: () => Promise<PickedItem | null>;
	pickTrailer: () => Promise<PickedItem | null>;
}

export interface PaletteEntry {
	type: string;
	desc: string;
	help?: string;
}

export const HELP = {
	trailer_rule:
		'Picks the set number of trailers automatically each time the playlist is ' +
		"generated - optionally matched to the feature's genre, certification or release year.",
	command_hold:
		'Instant commands (Hold off) fire invisibly as the rundown reaches this point, ' +
		'with nothing on screen. Hold shows a black screen until the command finishes ' +
		'and its minimum duration has passed, then the show moves on.'
} as const;

/** What a command targets, as its provider describes it (e.g. "POST http://…"). */
export function commandTarget(cmd: CommandInfo | null | undefined): string {
	return cmd?.summary ?? '';
}

export function commandSummary(cmd: CommandInfo | null | undefined, holdBlack: boolean): string {
	if (!cmd) return 'No command selected';
	const mode = holdBlack
		? cmd.duration
			? `Holds black ≥${cmd.duration}s`
			: 'Holds black while it runs'
		: 'Fires before the next item';
	return [cmd.provider_label, mode, commandTarget(cmd)].filter(Boolean).join(' · ');
}

export function filterDescription(content: BlockContent): string {
	const filters: string[] = [];
	if (content.genre_names?.length) filters.push(content.genre_names.join(', '));
	if (content.certification) filters.push(content.certification);
	if (content.year_from && content.year_to) filters.push(`${content.year_from}-${content.year_to}`);
	else if (content.year_from) filters.push(`${content.year_from}+`);
	else if (content.year_to) filters.push(`≤${content.year_to}`);
	if (content.runtime_from && content.runtime_to)
		filters.push(`${content.runtime_from}-${content.runtime_to} min`);
	else if (content.runtime_from) filters.push(`≥${content.runtime_from} min`);
	else if (content.runtime_to) filters.push(`≤${content.runtime_to} min`);
	return filters.join(', ');
}
