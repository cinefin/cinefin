// Hand-written types mirrored from the backend serializers (details dicts are
// untyped in the schema). GOTCHA: GET /programmes/{id}/playlist has an OpenAPI
// component-name collision — the playout router's PlaylistItemSchema/etc. win
// in the exported doc, so the generated types describe the wrong payload;
// ProgrammePlaylist below is this endpoint's real shape. Delete once the
// backend renames one side of the collision.

export interface SelectedAudioTrack {
	language?: string | null;
	codec?: string | null;
	channels?: number | null;
}

export interface SelectedSubtitleTrack {
	language?: string | null;
	forced?: boolean;
	sdh?: boolean;
}

// A union-ish bag keyed by item type.
export interface ProgrammeItemDetails {
	// movie
	movie_id?: number;
	missing?: boolean;
	year?: number | null;
	certification?: string | null;
	audio_track?: number | null;
	subtitle_track?: number | null;
	thumbnail_url?: string | null;
	director?: string | null;
	synopsis?: string | null;
	resolution?: string | null;
	file_size?: number | null;
	file_path?: string | null;
	selected_audio_track?: SelectedAudioTrack | null;
	selected_subtitle_track?: SelectedSubtitleTrack | null;
	// trailer_rule (explicit)
	count?: number;
	genre_ids?: number[];
	certificate_ceiling?: string | null;
	trailer_tag_name?: string | null;
	// trailer_rule (bound to a random movie)
	match_genres?: boolean;
	match_certification?: boolean;
	year_delta?: number;
	// bumper
	tag_id?: number;
	tag_name?: string;
	// certification
	for_random_movie?: boolean;
	// random_movie
	genre_names?: string[];
	year_from?: number | null;
	year_to?: number | null;
	matching_count?: number;
}

export interface ProgrammeItem {
	id: number;
	order: number;
	type: string;
	title: string;
	// Named "runtime" on the wire but holds SECONDS.
	runtime: number;
	details: ProgrammeItemDetails;
}

export interface PlaylistItemMetadata {
	rule_based_selection?: boolean;
	match_tier?: number;
	match_tier_name?: string;
	reference_movie?: string;
	matched_full?: number;
	requested?: number;
	year?: number | null;
}

export interface ProgrammePlaylistItemDetails {
	programme_block_id?: number | null;
	metadata?: PlaylistItemMetadata | null;
	[key: string]: unknown;
}

export interface ProgrammePlaylistItem {
	order: number;
	file_path: string;
	duration: number | null;
	title: string;
	type: string;
	details: ProgrammePlaylistItemDetails;
}

export interface ProgrammePlaylist {
	programme_id: number;
	programme_name: string;
	total_items: number;
	total_duration: number;
	items: ProgrammePlaylistItem[];
}
