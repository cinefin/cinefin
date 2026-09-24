/**
 * Shared playout status feed (topbar lamp, playout bar, dashboard, remote).
 * Rides the real-time WebSocket "playout" channel. Subscribe from an $effect.
 * WebSocket-only, no interval fallback: if the socket is down the clock stops
 * rather than masking a dead connection (which would hide a broken proxy).
 */
import { api, toApiError, unwrap, type ApiError } from '$lib/api/client';
import type { PlayoutStatus } from '$lib/api/refinements';
import { realtime, type RealtimeMessage } from '$lib/realtime.svelte';

class PlayoutStore {
	status = $state<PlayoutStatus | null>(null);
	error = $state<ApiError | null>(null);
	loaded = $state(false);

	#subscribers = 0;
	#unsub: (() => void) | null = null;

	subscribe(): () => void {
		this.#subscribers += 1;
		if (this.#subscribers === 1) {
			void this.refresh(); // instant first paint; the socket takes over
			this.#unsub = realtime.subscribe({
				channel: 'playout',
				onMessage: (msg: RealtimeMessage) => {
					this.status = msg.data as PlayoutStatus;
					this.error = null;
					this.loaded = true;
				}
			});
		}
		return () => {
			this.#subscribers -= 1;
			if (this.#subscribers === 0) {
				this.#unsub?.();
				this.#unsub = null;
			}
		};
	}

	async refresh(): Promise<void> {
		try {
			const data = await unwrap(api.GET('/api/v2/playout/status'));
			this.status = (data ?? null) as PlayoutStatus | null;
			this.error = null;
		} catch (e) {
			this.error = toApiError(e);
		} finally {
			this.loaded = true;
		}
	}
}

export const playout = new PlayoutStore();
