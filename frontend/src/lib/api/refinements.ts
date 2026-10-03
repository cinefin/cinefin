/**
 * Hand-written refinements for endpoints whose generated types are loose (backend fields typed
 * as `dict`/untyped). Mirrored from the backend serializers — never guessed. Delete an entry
 * once the backend schema tightens.
 */

/** TrailerStatsDataSchema.statistics — TrailerService.get_statistics() (backend types it as dict). */
export interface TrailerStatistics {
	total_trailers: number;
	by_year?: Record<string, number>;
	by_rating?: Record<string, number>;
	api_key_configured?: boolean;
}
