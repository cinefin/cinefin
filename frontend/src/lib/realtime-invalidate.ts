/**
 * Bridge: the real-time WebSocket's `invalidate` channel → the in-app invalidate() bus.
 * On every (re)connect it invalidates the full set once, since a disconnected client missed
 * the deltas emitted meanwhile (each producer only diffs from the moment it connected).
 * Mounted once from the root layout; subscriber-counted.
 */
import { invalidate, type ResourceKey } from '$lib/invalidate';
import { realtime, type RealtimeMessage } from '$lib/realtime.svelte';

const ALL_KEYS: ResourceKey[] = [
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
];
const KNOWN = new Set<string>(ALL_KEYS);

let unsub: (() => void) | null = null;
let refs = 0;

/** Start the bridge (idempotent, subscriber-counted). Return from an `$effect` to release. */
export function startInvalidateBridge(): () => void {
	refs += 1;
	if (!unsub) {
		unsub = realtime.subscribe({
			channel: 'invalidate',
			onConnect: () => invalidate(ALL_KEYS),
			onMessage: (msg: RealtimeMessage) => {
				const keys = ((msg.keys as string[]) ?? []).filter((k) => KNOWN.has(k)) as ResourceKey[];
				if (keys.length) invalidate(keys);
			}
		});
	}
	return () => {
		refs -= 1;
		if (refs === 0) {
			unsub?.();
			unsub = null;
		}
	};
}
