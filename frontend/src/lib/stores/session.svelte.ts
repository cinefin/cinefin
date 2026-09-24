/**
 * Shell session state: the running version and whether the auth gate is
 * enforced right now. Fetched once per app boot; both degrade quietly (version
 * stays unknown, the Log out control stays hidden).
 */
import { api, toApiError, unwrap } from '$lib/api/client';

/** GET /api/v2/version — a plain dict, no envelope. */
interface VersionPayload {
	version: string;
	commit: string;
}

class SessionStore {
	version = $state<string | null>(null);
	authActive = $state(false);
	#started = false;

	/** Idempotent: later callers get the cached state. */
	load() {
		if (this.#started) return;
		this.#started = true;
		void this.#loadVersion();
		void this.#loadSecurity();
	}

	async #loadVersion() {
		try {
			const result = await api.GET('/api/v2/version');
			if (result.error !== undefined || !result.data) {
				throw toApiError(result.error, result.response);
			}
			const payload = result.data as unknown as VersionPayload;
			this.version = payload.version || null;
		} catch {
			this.version = null;
		}
	}

	async #loadSecurity() {
		try {
			const state = await unwrap(api.GET('/api/v2/security/'));
			this.authActive = Boolean(state.auth_active);
		} catch {
			this.authActive = false;
		}
	}
}

export const session = new SessionStore();
