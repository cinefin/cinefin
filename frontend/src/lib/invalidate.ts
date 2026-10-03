/** invalidate() — the cross-page "this resource changed" pub/sub bus (no query cache library). */

/** Coarse resource names (not per-id) a view subscribes to / a mutation touches; some are named
 *  only by the real-time WebSocket's `invalidate` channel. */
export const RESOURCE_KEYS = [
	'schedules',
	'programmes',
	'templates',
	'titles',
	'movies',
	'trailers',
	'commands',
	'sync',
	'settings',
	'tickets',
	'playout-hosts',
	'runner',
	'health',
	'agent',
	'setup',
	'deploy'
] as const;
export type ResourceKey = (typeof RESOURCE_KEYS)[number];

type Listener = () => void;

const listeners = new Map<ResourceKey, Set<Listener>>();

/** Subscribe `fn` to one or more keys. Returns an unsubscribe — call it on teardown. */
export function onInvalidate(keys: ResourceKey | ResourceKey[], fn: Listener): () => void {
	const arr = Array.isArray(keys) ? keys : [keys];
	for (const k of arr) {
		let set = listeners.get(k);
		if (!set) listeners.set(k, (set = new Set()));
		set.add(fn);
	}
	return () => {
		for (const k of arr) listeners.get(k)?.delete(fn);
	};
}

/** Announce a change. Every subscriber of any named key fires once, even across multiple keys. */
export function invalidate(keys: ResourceKey | ResourceKey[]): void {
	const fired = new Set<Listener>();
	for (const k of Array.isArray(keys) ? keys : [keys]) {
		for (const fn of listeners.get(k) ?? []) {
			if (fired.has(fn)) continue;
			fired.add(fn);
			try {
				fn();
			} catch {
				/* a broken subscriber must not sink the rest */
			}
		}
	}
}
