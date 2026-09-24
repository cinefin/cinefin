/**
 * Hand-written refinements for endpoints whose generated types are loose (backend fields typed
 * as `dict`/untyped). Mirrored from the backend serializers — never guessed. Delete an entry
 * once the backend schema tightens.
 */

/** PlayoutStatusDataSchema.data — comprehensive_status() payload. */
export interface PlayoutStatus {
	programme: {
		id: number;
		name: string;
		description?: string;
		runtime_minutes?: number;
		runtime_formatted?: string;
		block_count?: number;
		state: string;
		created_at?: string | null;
	} | null;
	playback?: {
		state: string;
		position: number;
		duration: number;
		remaining?: number;
		percentage?: number;
	} | null;
	current_item?: {
		type: string;
		position: number;
		file: string;
		title: string | null;
		name?: string;
		details?: Record<string, unknown>;
	} | null;
	next_item?: {
		type: string;
		title: string | null;
		duration: number | null;
	} | null;
	/** Programme-wide playlist timing (PlaylistStatusSchema). */
	playlist?: {
		current_position?: number | null;
		total_items?: number;
		progress_percentage?: number;
		programme_total_duration?: number;
		programme_elapsed_time?: number;
		programme_remaining_time?: number;
		programme_time_percentage?: number;
		mpv_info?: Record<string, unknown>;
	} | null;
	/** True while a hold-black command item is holding the screen. While it is,
	 * `playback.position/duration` report the command's dwell, not MPV's clock. */
	executing_command?: boolean;
}

/**
 * One enhanced item from GET /playout/playlist. The exported OpenAPI schema collapses it with
 * mpv_ninja's schema of the same name, so the generated type is wrong — this pins the shape.
 */
export interface PlayoutPlaylistItem {
	index: number;
	title?: string | null;
	/** A stream URL. */
	file?: string;
	type?: string;
	duration?: number | null;
	current?: boolean;
	/** Always serialized; null for pre-show items (before the programme offset). */
	programme_position: number | null;
	details?: { metadata?: Record<string, unknown>; [extra: string]: unknown };
}

/** PlaylistDataSchema.data — GET /playout/playlist payload. */
export interface PlayoutPlaylistData {
	playlist: PlayoutPlaylistItem[];
	current_index?: number | null;
	programme_offset?: number;
	total_items?: number;
	total_duration?: number;
	elapsed_time?: number;
	remaining_time?: number;
}

/** TrailerStatsDataSchema.statistics — TrailerService.get_statistics() (backend types it as dict). */
export interface TrailerStatistics {
	total_trailers: number;
	by_year?: Record<string, number>;
	by_rating?: Record<string, number>;
	api_key_configured?: boolean;
}
