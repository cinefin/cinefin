/**
 * Shared playout status feed on the WebSocket "playout" channel; read it through
 * `$lib/playout/phase`. No interval fallback: a dead socket stops the clock rather than hiding it,
 * and while Cinefin can't be reached (`stale`) the last status stands with no actions allowed.
 */
import { api, toApiError, unwrap, type ApiError } from '$lib/api/client';
import type { components } from '$lib/api/types.gen';
import type { PlayoutStatus } from '$lib/playout/phase';
import { realtime, type RealtimeMessage } from '$lib/realtime.svelte';
import { refCounted } from './refcount';

export type ControlBody = components['schemas']['ControlPlayoutSchema'];

class PlayoutStore {
	#live = $state<PlayoutStatus | null>(null);
	/** True while Cinefin can't be reached, so `status` is the last one seen. */
	stale = $derived(realtime.down);
	status = $derived(this.stale && this.#live ? { ...this.#live, actions: [] } : this.#live);
	error = $state<ApiError | null>(null);
	loaded = $state(false);

	subscribe = refCounted(() => {
		void this.refresh(); // instant first paint; the socket takes over
		return realtime.subscribe({
			channel: 'playout',
			onMessage: (msg: RealtimeMessage) => this.#adopt(msg.data as PlayoutStatus)
		});
	});

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
		const id = this.#live?.player?.id;
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
		this.#live = status;
		this.error = null;
		this.loaded = true;
	}
}

export const playout = new PlayoutStore();
