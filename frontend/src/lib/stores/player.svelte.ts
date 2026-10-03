/**
 * Player feeds for the remote console and the playout bar: the `mpv` status
 * store and the `playlist` store, both extending the shared `playout` feed.
 * Both degrade quietly — a failed poll reports as null and the next tick retries.
 */
import { api, unwrap } from '$lib/api/client';
import type { components } from '$lib/api/types.gen';
import { playout } from './playout.svelte';

export type MpvStatusData = components['schemas']['MPVStatusDataSchema'];
export type PlayoutPlaylistData = components['schemas']['PlaylistDataSchema'];
export type PlayoutPlaylistItem = PlayoutPlaylistData['playlist'][number];

// Signature re-check cadence (local state only — no network unless it changed).
const SIGNATURE_CHECK_MS = 1000;
// Slow heartbeat so connection state + tracks stay fresh while nothing changes;
// the live clock rides the playout SSE, not this.
const MPV_HEARTBEAT_MS = 15_000;

class MpvStore {
	/** Null = the endpoint failed (treat as disconnected). */
	status = $state<MpvStatusData | null>(null);
	loaded = $state(false);

	#timer: ReturnType<typeof setInterval> | null = null;
	#subscribers = 0;
	#inFlight = false;
	#unsubPlayout: (() => void) | null = null;
	/** undefined forces the next check to fetch. */
	#signature: string | null | undefined = null;
	#lastFetch = 0;

	subscribe(): () => void {
		this.#subscribers += 1;
		if (this.#subscribers === 1) {
			// Gate off the shared playout feed: it reports item changes over SSE.
			this.#unsubPlayout = playout.subscribe();
			this.#signature = undefined;
			void this.#check();
			this.#timer = setInterval(() => void this.#check(), SIGNATURE_CHECK_MS);
		}
		return () => {
			this.#subscribers -= 1;
			if (this.#subscribers === 0) {
				if (this.#timer) {
					clearInterval(this.#timer);
					this.#timer = null;
				}
				this.#unsubPlayout?.();
				this.#unsubPlayout = null;
			}
		};
	}

	async refresh(): Promise<void> {
		this.#signature = undefined;
		await this.#check();
	}

	// What is on screen; a change means the tracks may have changed.
	#computeSignature(): string | null {
		const p = playout.status;
		return p
			? `${p.phase}:${p.screen}:${p.playlist?.mpv_position ?? p.manual?.position ?? ''}`
			: null;
	}

	async #check(): Promise<void> {
		const sig = this.#computeSignature();
		const heartbeatDue = Date.now() - this.#lastFetch >= MPV_HEARTBEAT_MS;
		if (sig === this.#signature && !heartbeatDue) return;
		this.#signature = sig;
		await this.#fetch();
	}

	async #fetch(): Promise<void> {
		if (this.#inFlight) return;
		this.#inFlight = true;
		this.#lastFetch = Date.now();
		try {
			this.status = (await unwrap(api.GET('/api/v2/mpv/status'))) ?? null;
		} catch {
			this.status = null;
		} finally {
			this.loaded = true;
			this.#inFlight = false;
		}
	}
}

export const mpv = new MpvStore();

class PlaylistStore {
	data = $state<PlayoutPlaylistData | null>(null);

	/** undefined forces the next check to fetch. */
	#signature: string | null | undefined = null;
	#timer: ReturnType<typeof setInterval> | null = null;
	#subscribers = 0;
	#inFlight = false;
	#unsubPlayout: (() => void) | null = null;

	subscribe(): () => void {
		this.#subscribers += 1;
		if (this.#subscribers === 1) {
			// Signature derives from the shared playout feed — keep it live.
			this.#unsubPlayout = playout.subscribe();
			this.#signature = undefined;
			void this.#check();
			this.#timer = setInterval(() => void this.#check(), SIGNATURE_CHECK_MS);
		}
		return () => {
			this.#subscribers -= 1;
			if (this.#subscribers === 0) {
				if (this.#timer) {
					clearInterval(this.#timer);
					this.#timer = null;
				}
				this.#unsubPlayout?.();
				this.#unsubPlayout = null;
			}
		};
	}

	refresh(): void {
		this.#signature = undefined;
		void this.#check();
	}

	// Refetch only on a programme/count/position change, not every tick.
	#computeSignature(): string | null {
		const p = playout.status;
		if (p?.programme?.id != null) {
			return `${p.programme.id}:${p.playlist?.mpv_position ?? ''}:${p.playlist?.total_items ?? ''}`;
		}
		return null;
	}

	async #check(): Promise<void> {
		if (this.#inFlight) return;
		const sig = this.#computeSignature();
		if (sig === this.#signature) return;
		this.#signature = sig;

		if (sig === null) {
			this.data = null;
			return;
		}

		this.#inFlight = true;
		try {
			this.data = (await unwrap(api.GET('/api/v2/playout/playlist'))) ?? null;
		} catch {
			this.data = null;
		} finally {
			this.#inFlight = false;
		}
	}
}

export const playlist = new PlaylistStore();
