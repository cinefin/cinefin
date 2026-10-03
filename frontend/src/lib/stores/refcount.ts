/** Subscriber counting: `start` runs on the first subscribe, its cleanup on the last unsubscribe. */
export function refCounted(start: () => () => void): () => () => void {
	let subscribers = 0;
	let stop: (() => void) | null = null;
	return () => {
		if (subscribers++ === 0) stop = start();
		return () => {
			if (--subscribers === 0) {
				stop?.();
				stop = null;
			}
		};
	};
}
