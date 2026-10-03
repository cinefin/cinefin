/**
 * Shared playout status feed (topbar lamp, playout bar, dashboard, remote, kiosk).
 * Rides the real-time WebSocket "playout" channel. Subscribe from an $effect.
 * WebSocket-only, no interval fallback: if the socket is down the clock stops
 * rather than masking a dead connection (which would hide a broken proxy).
 *
 * Read it through `$lib/playout/phase` (lamp, bar lines, enabled buttons), and act
 * through `control()` and `cue()`: every transport button goes to POST
 * /playout/control, which refuses (409) an action the status doesn't allow.
 */
import { api, toApiError, unwrap, type ApiError } from '$lib/api/client';
import type { components } from '$lib/api/types.gen';
import type { PlayoutStatus } from '$lib/playout/phase';
import { realtime, type RealtimeMessage } from '$lib/realtime.svelte';

export type ControlBody = components['schemas']['ControlPlayoutSchema'];

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
				onMessage: (msg: RealtimeMessage) => this.#adopt(msg.data as PlayoutStatus)
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
			this.#adopt((await unwrap(api.GET('/api/v2/playout/status'))) ?? null);
		} catch (e) {
			this.error = toApiError(e);
		} finally {
			this.loaded = true;
		}
	}

	/** Run a transport action; the answer is the new status. Throws ApiError (409 when not allowed). */
	async control(body: ControlBody): Promise<void> {
		this.#adopt((await unwrap(api.POST('/api/v2/playout/control', { body }))) ?? null);
	}

	/** Cue a programme (POST /playout/load); returns its pre-flight warnings. */
	async cue(programmeId: number): Promise<string[]> {
		const data = await unwrap(
			api.POST('/api/v2/playout/load', {
				body: { programme_id: programmeId, generate_playlist: true }
			})
		);
		void this.refresh();
		return data?.warnings ?? [];
	}

	/** Show or hide the active player's status line over standby (PATCH the host). */
	async setStatusLine(show: boolean): Promise<void> {
		const id = this.status?.player?.id;
		if (id == null) return;
		await unwrap(
			api.PATCH('/api/v2/playout/hosts/{host_id}', {
				params: { path: { host_id: id } },
				body: { show_status: show }
			})
		);
		await this.refresh();
	}

	#adopt(status: PlayoutStatus | null): void {
		this.status = status;
		this.error = null;
		this.loaded = true;
	}
}

export const playout = new PlayoutStore();
