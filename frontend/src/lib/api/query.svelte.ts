/**
 * query() — the page data-loading convention (runes). A Query holds { data, error, loading }
 * around an async loader.
 * - load()    — full (re)load, shows the loading state (initial load, user-visible retries).
 * - refresh() — background refetch: keeps last good data, swaps silently; a failed refresh keeps
 *               the stale data and records the error.
 * - live(opts) — background polling that pauses while hidden and refetches on wake; with `{ keys }`
 *               also refetches when another page invalidates one of those resources.
 * - invalidatesOn(keys) — refetch on cross-page invalidation only (no polling).
 */
import { ApiError, toApiError } from './client';
import { liveRefresh, type LiveRefreshOptions } from '../live.svelte';
import { onInvalidate, type ResourceKey } from '../invalidate';

export class Query<T> {
	data = $state<T | undefined>(undefined);
	error = $state<ApiError | null>(null);
	loading = $state(true);

	#loader: () => Promise<T>;
	#seq = 0;

	constructor(loader: () => Promise<T>) {
		this.#loader = loader;
	}

	async load(): Promise<void> {
		this.loading = true;
		this.error = null;
		await this.#run();
		this.loading = false;
	}

	async refresh(): Promise<void> {
		await this.#run();
	}

	/** Background refreshes while visible + one on wake (skips ticks racing a visible load), plus
	 *  refetch on invalidation of `opts.keys`. Returns the stop function. */
	live(opts?: LiveRefreshOptions & { keys?: ResourceKey[] }): () => void {
		const stopLive = liveRefresh(() => (this.loading ? undefined : this.refresh()), opts);
		const stopInv = opts?.keys?.length ? this.invalidatesOn(opts.keys) : undefined;
		return () => {
			stopLive();
			stopInv?.();
		};
	}

	/** Refetch silently whenever another page invalidates any of these resources (no polling). */
	invalidatesOn(keys: ResourceKey[]): () => void {
		return onInvalidate(keys, () => {
			if (!this.loading) void this.refresh();
		});
	}

	async #run(): Promise<void> {
		const seq = ++this.#seq;
		try {
			const result = await this.#loader();
			if (seq !== this.#seq) return; // superseded by a newer call
			this.data = result;
			this.error = null;
		} catch (e) {
			if (seq !== this.#seq) return;
			this.error = toApiError(e);
		}
	}
}

export function query<T>(loader: () => Promise<T>): Query<T> {
	const q = new Query(loader);
	void q.load();
	return q;
}
