/**
 * "Can Cinefin reach the playout host?" — the reachability feed behind the
 * dashboard's playout notice. Two distinct failure states with different fixes:
 * `unconfigured` (no active PlayoutHost) vs `unreachable` (host set, agent
 * silent) — `GET /playout/agent/status` separates them (`enabled` vs
 * `reachable`). Subscribe from an $effect and return the cleanup.
 */
import { api, unwrap } from '$lib/api/client';
import { onInvalidate } from '$lib/invalidate';

export type PlayoutReachState = 'ok' | 'unconfigured' | 'unreachable';

class PlayoutReachStore {
	/** Null while unknown (first load, or every poll so far failed to reach us). */
	state = $state<PlayoutReachState | null>(null);
	hostName = $state('');
	hostUrl = $state('');
	/** 0 = add one, >0 = none of them is active. */
	hostCount = $state(0);
	checked = $state(false);

	#unsub: (() => void) | null = null;
	#subscribers = 0;
	#inFlight = false;
	/** Consecutive unreachable readings, so one blip can't raise the notice. */
	#strikes = 0;

	subscribe(): () => void {
		this.#subscribers += 1;
		if (this.#subscribers === 1) {
			void this.refresh();
			this.#unsub = onInvalidate('agent', () => void this.refresh());
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
		// A poll in flight keeps the last verdict on screen — no flicker or stampede.
		if (this.#inFlight) return;
		this.#inFlight = true;
		try {
			const agent = await unwrap(api.GET('/api/v2/playout/agent/status'));
			if (agent?.reachable) {
				this.#strikes = 0;
				this.state = 'ok';
				return;
			}
			if (!agent?.enabled) {
				// A DB fact, not a network guess — trust it straight away.
				this.#strikes = 0;
				await this.#loadHost();
				this.state = 'unconfigured';
				return;
			}
			// Configured but silent: trust the first reading on a fresh load, but
			// once seen healthy require two in a row so a restart doesn't flap.
			this.#strikes += 1;
			if (this.#strikes >= (this.state === 'ok' ? 2 : 1)) {
				await this.#loadHost();
				this.state = 'unreachable';
			}
		} catch {
			// Our own API didn't answer — no evidence about the host. Keep the last verdict.
		} finally {
			this.checked = true;
			this.#inFlight = false;
		}
	}

	async #loadHost(): Promise<void> {
		try {
			const hosts = (await unwrap(api.GET('/api/v2/playout/hosts'))) ?? [];
			const active = hosts.find((h) => h.is_active) ?? null;
			this.hostCount = hosts.length;
			this.hostName = active?.name ?? '';
			// Socket path for a local mpv host, the agent URL otherwise.
			this.hostUrl =
				(active?.kind === 'local_socket' ? active?.socket_path : active?.base_url) ?? '';
		} catch {
			/* leave whatever we last knew */
		}
	}
}

export const playoutReach = new PlayoutReachStore();
