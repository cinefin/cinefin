/**
 * Bridge: the real-time WebSocket's `invalidate` channel → the in-app invalidate() bus. On every
 * (re)connect it invalidates everything once, since a disconnected client missed the deltas.
 */
import { invalidate, RESOURCE_KEYS, type ResourceKey } from '$lib/invalidate';
import { realtime, type RealtimeMessage } from '$lib/realtime.svelte';

const KNOWN = new Set<string>(RESOURCE_KEYS);

/** Start the bridge (mounted once from the root layout). Return from an `$effect` to release. */
export function startInvalidateBridge(): () => void {
	return realtime.subscribe({
		channel: 'invalidate',
		onConnect: () => invalidate([...RESOURCE_KEYS]),
		onMessage: (msg: RealtimeMessage) => {
			const keys = ((msg.keys as string[]) ?? []).filter((k) => KNOWN.has(k)) as ResourceKey[];
			if (keys.length) invalidate(keys);
		}
	});
}
