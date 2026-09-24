/**
 * liveRefresh() — calls `fn` silently on a cadence while the tab is visible, and once (debounced)
 * whenever it wakes (visibility/focus/persisted pageshow). Never fires while hidden. The callback
 * is a background refetch by contract (keep last good data, degrade quietly); post-mutation
 * refreshes are the handler's job, not this helper's. Returns a stop function.
 */
export interface LiveRefreshOptions {
	everyMs?: number;
}

/** How long a wake-up waits for its twin event before firing once. */
const WAKE_DEBOUNCE_MS = 150;

export function liveRefresh(fn: () => unknown, opts: LiveRefreshOptions = {}): () => void {
	const everyMs = opts.everyMs ?? 30_000;
	let timer: ReturnType<typeof setInterval> | undefined;
	let wake: ReturnType<typeof setTimeout> | undefined;

	const visible = () => document.visibilityState === 'visible';

	function fire() {
		if (!visible()) return;
		try {
			const r = fn();
			if (r instanceof Promise) r.catch(() => {}); // a missed tick is not an error surface
		} catch {
			/* ditto for sync throws */
		}
	}

	function startInterval() {
		stopInterval();
		timer = setInterval(fire, everyMs);
	}

	function stopInterval() {
		if (timer !== undefined) clearInterval(timer);
		timer = undefined;
	}

	/** Fire once (debounced), then restart the cadence so the next tick is a full period away. */
	function onWake() {
		if (!visible()) return;
		clearTimeout(wake);
		wake = setTimeout(fire, WAKE_DEBOUNCE_MS);
		startInterval();
	}

	function onVisibility() {
		if (visible()) {
			onWake();
		} else {
			clearTimeout(wake);
			stopInterval();
		}
	}

	/** bfcache restore paints a stale in-memory snapshot without refetching — treat as a wake. */
	function onPageShow(e: PageTransitionEvent) {
		if (e.persisted) onWake();
	}

	document.addEventListener('visibilitychange', onVisibility);
	window.addEventListener('focus', onWake);
	window.addEventListener('pageshow', onPageShow);
	if (visible()) startInterval();

	return () => {
		clearTimeout(wake);
		stopInterval();
		document.removeEventListener('visibilitychange', onVisibility);
		window.removeEventListener('focus', onWake);
		window.removeEventListener('pageshow', onPageShow);
	};
}
