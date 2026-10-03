/**
 * Player feeds for the remote and the playout bar: `mpv` status and the `playlist`, both refetched
 * when the shared `playout` feed says what is on screen changed. A failed fetch reports as null.
 */
import { api, unwrap } from '$lib/api/client';
import type { components } from '$lib/api/types.gen';
import type { PlayoutStatus } from '$lib/playout/phase';
import { playout } from './playout.svelte';
import { refCounted } from './refcount';

type MpvStatusData = components['schemas']['MPVStatusDataSchema'];
type PlayoutPlaylistData = components['schemas']['PlaylistDataSchema'];
export type PlayoutPlaylistItem = PlayoutPlaylistData['playlist'][number];

// Signature re-check cadence (local state only — no network unless it changed).
const SIGNATURE_CHECK_MS = 1000;

/** A feed refetched when a signature of the playout status changes (checked every second). */
class SignatureFeed<T> {
	/** Null = nothing loaded, or the endpoint failed. */
	data = $state<T | null>(null);

	/** undefined forces the next check to fetch. */
	#signature: string | null | undefined = null;
	#inFlight = false;
	#lastFetch = 0;
	#sign: (p: PlayoutStatus | null) => string | null;
	#fetch: () => Promise<T | undefined>;
	#heartbeatMs: number;

	/** With a heartbeat, an unchanged signature still refetches that often; without one, a null
	 *  signature clears the data instead of fetching. */
	constructor(
		sign: (p: PlayoutStatus | null) => string | null,
		fetch: () => Promise<T | undefined>,
		heartbeatMs = 0
	) {
		this.#sign = sign;
		this.#fetch = fetch;
		this.#heartbeatMs = heartbeatMs;
	}

	subscribe = refCounted(() => {
		const unsubPlayout = playout.subscribe();
		this.#signature = undefined;
		void this.#check();
		const timer = setInterval(() => void this.#check(), SIGNATURE_CHECK_MS);
		return () => {
			clearInterval(timer);
			unsubPlayout();
		};
	});

	async refresh(): Promise<void> {
		this.#signature = undefined;
		await this.#check();
	}

	async #check(): Promise<void> {
		if (!this.#heartbeatMs && this.#inFlight) return;
		const sig = this.#sign(playout.status);
		const fresh = Date.now() - this.#lastFetch < this.#heartbeatMs;
		if (sig === this.#signature && (!this.#heartbeatMs || fresh)) return;
		this.#signature = sig;
		if (!this.#heartbeatMs && sig === null) {
			this.data = null;
			return;
		}
		if (this.#inFlight) return;
		this.#inFlight = true;
		this.#lastFetch = Date.now();
		try {
			this.data = (await this.#fetch()) ?? null;
		} catch {
			this.data = null;
		} finally {
			this.#inFlight = false;
		}
	}
}

// What is on screen; a change means the tracks may have changed. A slow heartbeat keeps the
// connection state and tracks fresh; the live clock rides the playout feed.
export const mpv = new SignatureFeed<MpvStatusData>(
	(p) =>
		p ? `${p.phase}:${p.screen}:${p.playlist?.mpv_position ?? p.manual?.position ?? ''}` : null,
	() => unwrap(api.GET('/api/v2/mpv/status')),
	15_000
);

// Refetch only on a programme/count/position change, not every tick.
export const playlist = new SignatureFeed<PlayoutPlaylistData>(
	(p) =>
		p?.programme?.id != null
			? `${p.programme.id}:${p.playlist?.mpv_position ?? ''}:${p.playlist?.total_items ?? ''}`
			: null,
	() => unwrap(api.GET('/api/v2/playout/playlist'))
);
