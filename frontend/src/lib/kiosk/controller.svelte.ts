/**
 * Kiosk display controller — the reactive core of the 24/7 wall display.
 *
 * Unattended-display discipline: every fetch failure is silent — keep the last good state, the next signal self-heals. No toasts, no error splashes.
 * Takeover precedence (strongest first): playout > countdown > night > base layout. A live playout wakes a sleeping display.
 * Preference resolution, weakest first: defaults < server Kiosk settings < per-screen picker overrides (localStorage) < URL parameters.
 * Deploy detection: the display payload carries a version stamp; the boot stamp is held fixed, and a differing one on refresh reloads for new code (deferred under a takeover).
 */
import { replaceState } from '$app/navigation';
import { api, unwrap } from '$lib/api/client';
import { onInvalidate } from '$lib/invalidate';
import { realtime, type RealtimeMessage } from '$lib/realtime.svelte';
import { started, type PlayoutStatus } from '$lib/playout/phase';
import { countdownClockText, fmtClock, isRunning, setClockFormat } from './time';
import type {
	KioskCinema,
	KioskDisplayData,
	KioskFilm,
	KioskFilmish,
	KioskMode,
	KioskPlayout,
	KioskPrefs,
	KioskScreening,
	KioskSettings
} from './types';

export const LAYOUTS = ['wall', 'spotlight', 'split', 'board', 'tonight', 'auto'];
// Removed layouts mapped to their nearest survivor, so saved settings keep working.
const LEGACY_LAYOUTS: Record<string, string> = {
	nownext: 'split',
	marquee: 'board',
	lightbox: 'spotlight'
};
// Ambient layouts only — board/tonight are purpose-built and read wrong in a cycle.
const ROTATE_ORDER = ['wall', 'spotlight', 'split'];
const OVERRIDES_KEY = 'cinefin.kiosk.overrides';
const LEGACY_PREFS_KEY = 'cinefin.kiosk.prefs';

const BOOT_RETRY_MS = 15000; // fast retry until the first display fetch lands
const START_GRACE_MS = 90000; // "Starting now" dwell before a missed start gives up
const AUTO_SPLIT_MS = 2 * 3600000; // auto layout: split when a showing is this close
const EXTRAPOLATE_S = 30; // the playout clock runs on without news this long, then holds

const DEFAULT_PREFS: KioskPrefs = {
	layout: 'wall',
	rotate: 0,
	clock: true,
	header: true,
	takeover: true,
	countdown: 30,
	night: false,
	nightStart: '01:00',
	nightEnd: '08:00',
	spotlightSecs: 12,
	wallPageSecs: 20,
	showtimes: true
};

function normalizeLayout(value: string): string {
	return LEGACY_LAYOUTS[value] || value;
}

/** Per-screen picker overrides: ONLY the keys this screen has changed. */
function loadOverrides(): Partial<KioskPrefs> {
	try {
		const stored = localStorage.getItem(OVERRIDES_KEY);
		if (stored) return JSON.parse(stored);
		// Migrate the pre-overrides full-blob prefs, if this screen has one.
		const legacy = localStorage.getItem(LEGACY_PREFS_KEY);
		if (legacy) {
			localStorage.removeItem(LEGACY_PREFS_KEY);
			const parsed = JSON.parse(legacy);
			try {
				localStorage.setItem(OVERRIDES_KEY, JSON.stringify(parsed));
			} catch {
				/* ignore */
			}
			return parsed;
		}
	} catch {
		/* fall through */
	}
	return {};
}

export class KioskController {
	films = $state<KioskFilm[]>([]);
	screenings = $state<KioskScreening[]>([]);
	cinema = $state<KioskCinema | null>(null);
	/** True once the first display fetch has landed (until then: quiet boot). */
	booted = $state(false);
	playout = $state<KioskPlayout | null>(null);
	now = $state(Date.now());
	layout = $state('wall');
	rotateChoice = $state<string | null>(null);
	autoChoice = $state('wall');
	prefs = $state<KioskPrefs>({ ...DEFAULT_PREFS });

	#serverSettings: Partial<KioskSettings> = {};
	#overrides: Partial<KioskPrefs> = loadOverrides();
	#bootReloadKey = ''; // deploy stamp the page booted with — held fixed
	#lastDisplayJSON = '';
	#stops: (() => void)[] = [];
	#bootRetryTimer: ReturnType<typeof setTimeout> | null = null;
	#rotateTimer: ReturnType<typeof setInterval> | null = null;
	#destroyed = false;

	/** Screenings that haven't ended yet, soonest first. */
	activeScreenings = $derived(
		this.screenings
			.filter((s) => s.end && Date.parse(s.end) > this.now)
			.toSorted((a, b) => Date.parse(a.start) - Date.parse(b.start))
	);

	playoutEngaged = $derived(!!(this.prefs.takeover && this.playout));

	// A just-passed start lingers for START_GRACE_MS so the scheduler can fire before the display gives up.
	countdownTarget = $derived.by((): KioskScreening | null => {
		if (!(this.prefs.countdown > 0)) return null;
		const next = this.activeScreenings.find((s) => Date.parse(s.start) + START_GRACE_MS > this.now);
		if (!next) return null;
		if (Date.parse(next.start) - this.now > this.prefs.countdown * 60000) return null;
		return next;
	});

	// True inside the configured quiet hours (the window may wrap midnight).
	nightNow = $derived.by((): boolean => {
		if (!this.prefs.night) return false;
		const toMins = (s: string) => {
			const parts = String(s).split(':');
			return (Number(parts[0]) || 0) * 60 + (Number(parts[1]) || 0);
		};
		const d = new Date(this.now);
		const cur = d.getHours() * 60 + d.getMinutes();
		const start = toMins(this.prefs.nightStart);
		const end = toMins(this.prefs.nightEnd);
		if (start === end) return false;
		return start < end ? cur >= start && cur < end : cur >= start || cur < end;
	});

	// Precedence: playout > countdown > night > base layout. A live playout wakes a sleeping display.
	mode = $derived.by((): KioskMode => {
		if (this.playoutEngaged) return 'playout';
		if (this.countdownTarget) return 'countdown';
		if (this.nightNow && !this.playout) return 'night';
		return 'layout';
	});

	effectiveLayout = $derived(
		this.layout === 'auto' ? this.autoChoice : this.rotateChoice || this.layout
	);

	// Programme-level on purpose: item changes must NOT crossfade the takeover; only a state flip / pause / new bill does.
	playoutKey = $derived.by((): string => {
		const p = this.playout;
		return p ? `${p.programmeName}:${p.phase}:${p.features.map((f) => f.id).join(',')}` : '';
	});

	headerClockText = $derived(fmtClock(new Date(this.now)));
	headerDateText = $derived(
		new Date(this.now).toLocaleDateString('en-GB', {
			weekday: 'long',
			day: 'numeric',
			month: 'long'
		})
	);

	init(): void {
		this.recomputePrefs();
		this.layout = this.prefs.layout;

		const tick = setInterval(() => (this.now = Date.now()), 1000);
		// Server state over the shared socket, no polling.
		this.#stops.push(
			() => clearInterval(tick),
			realtime.subscribe({
				channel: 'playout',
				onMessage: (msg: RealtimeMessage) => this.#adoptPlayoutStatus(msg.data as PlayoutStatus)
			}),
			onInvalidate('schedules', () => void this.#pollSchedules()),
			onInvalidate(['settings', 'movies', 'deploy'], () => void this.#refreshDisplay())
		);

		void this.#loadDisplay();
		void this.#pollSchedules();
		void this.#pollPlayout();
		this.#bindWakeLock();
		this.startRotation();
	}

	destroy(): void {
		this.#destroyed = true;
		this.#stops.forEach((stop) => stop());
		this.#stops = [];
		if (this.#bootRetryTimer) clearTimeout(this.#bootRetryTimer);
		if (this.#rotateTimer) clearInterval(this.#rotateTimer);
		this.#releaseWakeLock();
	}

	/** The display payload's server settings (snake_case) as pref candidates. */
	#serverPrefs(): Partial<KioskPrefs> {
		const s = this.#serverSettings;
		const out: Partial<KioskPrefs> = {};
		const layout = normalizeLayout(s.layout as string);
		if (LAYOUTS.includes(layout)) out.layout = layout;
		if (typeof s.rotate_minutes === 'number' && s.rotate_minutes >= 0)
			out.rotate = s.rotate_minutes;
		if (typeof s.header === 'boolean') out.header = s.header;
		if (typeof s.clock === 'boolean') out.clock = s.clock;
		if (typeof s.takeover === 'boolean') out.takeover = s.takeover;
		if (typeof s.countdown_minutes === 'number' && s.countdown_minutes >= 0)
			out.countdown = s.countdown_minutes;
		if (typeof s.night === 'boolean') out.night = s.night;
		if (typeof s.night_start === 'string') out.nightStart = s.night_start;
		if (typeof s.night_end === 'string') out.nightEnd = s.night_end;
		if (typeof s.show_showtimes === 'boolean') out.showtimes = s.show_showtimes;
		return out;
	}

	/** URL parameters — the strongest layer; a wall unit needs no touch setup. */
	#urlPrefs(): Partial<KioskPrefs> {
		const params = new URLSearchParams(window.location.search);
		const out: Partial<KioskPrefs> = {};
		const bool = (v: string | null) => ['1', 'true', 'on'].includes(String(v).toLowerCase());
		const hhmm = (v: string | null) => /^\d{1,2}:\d{2}$/.test(v || '');
		const mins = (v: string | null) => {
			const n = parseInt(v!, 10);
			return isNaN(n) || n < 0 ? null : n;
		};
		const layout = normalizeLayout(params.get('layout') || '');
		if (layout && LAYOUTS.includes(layout)) out.layout = layout;
		const rotate = mins(params.get('rotate'));
		if (rotate !== null) out.rotate = rotate;
		const countdown = mins(params.get('countdown'));
		if (countdown !== null) out.countdown = countdown;
		for (const key of ['header', 'clock', 'takeover', 'night', 'showtimes'] as const)
			if (params.has(key)) out[key] = bool(params.get(key));
		if (hhmm(params.get('nightstart'))) out.nightStart = params.get('nightstart')!;
		if (hhmm(params.get('nightend'))) out.nightEnd = params.get('nightend')!;
		const spot = mins(params.get('spotlight'));
		if (spot !== null && spot >= 5) out.spotlightSecs = spot;
		const page = mins(params.get('wallpage'));
		if (page !== null && page >= 5) out.wallPageSecs = page;
		return out;
	}

	/** Re-resolve defaults < server settings < picker overrides < URL. */
	recomputePrefs(): void {
		Object.assign(
			this.prefs,
			DEFAULT_PREFS,
			this.#serverPrefs(),
			this.#overrides,
			this.#urlPrefs()
		);
		// A stored override may still name a removed layout.
		this.prefs.layout = normalizeLayout(this.prefs.layout);
		if (!LAYOUTS.includes(this.prefs.layout)) this.prefs.layout = 'wall';
	}

	#saveOverrides(): void {
		try {
			localStorage.setItem(OVERRIDES_KEY, JSON.stringify(this.#overrides));
		} catch {
			/* storage full/blocked — overrides just won't persist */
		}
	}

	/** A picker change: persist as this screen's override and re-resolve. */
	setPref<K extends keyof KioskPrefs>(key: K, value: KioskPrefs[K]): void {
		this.#overrides[key] = value;
		this.#saveOverrides();
		this.recomputePrefs();
	}

	setLayout(layout: string): void {
		this.layout = layout;
		this.rotateChoice = null; // a deliberate pick restarts the rotation from it
		this.setPref('layout', layout);
		// Keep the URL authoritative so a reload (or power cycle) sticks.
		const url = new URL(window.location.href);
		url.searchParams.set('layout', layout);
		replaceState(url, {});
		this.startRotation();
	}

	/** Drop every override this screen's picker has made (URL params still win). */
	useServerDefaults(): void {
		for (const key of Object.keys(this.#overrides)) delete this.#overrides[key as keyof KioskPrefs];
		try {
			localStorage.removeItem(OVERRIDES_KEY);
		} catch {
			/* ignore */
		}
		const url = new URL(window.location.href);
		url.searchParams.delete('layout'); // setLayout pins it — unpin with the overrides
		replaceState(url, {});
		this.recomputePrefs();
		this.layout = this.prefs.layout;
		this.rotateChoice = null;
		this.startRotation();
	}

	// Global timer: takeovers only mask it, the cycle keeps its cadence. 'auto' ignores rotation.
	startRotation(): void {
		if (this.#rotateTimer) clearInterval(this.#rotateTimer);
		this.#rotateTimer = null;
		if (!(this.prefs.rotate > 0) || this.layout === 'auto') {
			this.rotateChoice = null;
			return;
		}
		this.#rotateTimer = setInterval(() => {
			const cur = ROTATE_ORDER.indexOf(this.effectiveLayout);
			this.rotateChoice = ROTATE_ORDER[(cur + 1) % ROTATE_ORDER.length];
		}, this.prefs.rotate * 60000);
	}

	async #fetchDisplay(): Promise<KioskDisplayData | null> {
		try {
			return await unwrap(api.GET('/api/v2/kiosk/display'));
		} catch {
			return null; // silent: a wall display never surfaces an error
		}
	}

	/** Initial load — retried quickly until it lands. */
	async #loadDisplay(): Promise<void> {
		const data = await this.#fetchDisplay();
		if (this.#destroyed) return;
		if (!data) {
			if (!this.booted)
				this.#bootRetryTimer = setTimeout(() => void this.#loadDisplay(), BOOT_RETRY_MS);
			return;
		}
		this.#adoptDisplay(data);
	}

	async #refreshDisplay(): Promise<void> {
		const data = await this.#fetchDisplay();
		if (!data || this.#destroyed) return;
		// Deploy landed: reload for new code (a 24/7 screen otherwise runs stale JS forever). Deferred under a takeover — the boot key stays fixed so the next refresh retries.
		if (
			data.reload_key &&
			this.#bootReloadKey &&
			data.reload_key !== this.#bootReloadKey &&
			this.mode !== 'playout' &&
			this.mode !== 'countdown'
		) {
			window.location.reload();
			return;
		}
		if (JSON.stringify(data) !== this.#lastDisplayJSON) this.#adoptDisplay(data);
	}

	#adoptDisplay(data: KioskDisplayData): void {
		this.#lastDisplayJSON = JSON.stringify(data);
		this.films = data.films ?? [];
		this.screenings = data.screenings ?? [];
		this.cinema = data.cinema ?? null;
		setClockFormat(data.cinema?.time_format);
		this.#serverSettings = data.settings ?? {};
		if (data.reload_key && !this.#bootReloadKey) this.#bootReloadKey = data.reload_key;
		// Server settings may have changed — re-resolve (overrides and URL params still win).
		this.recomputePrefs();
		this.layout = this.prefs.layout;
		this.autoChoice = this.#resolveAutoChoice();
		this.booted = true;
		this.startRotation();
	}

	/** Poll the (kiosk-public, read-only) schedules endpoint for fresh times. */
	async #pollSchedules(): Promise<void> {
		try {
			const data = await unwrap(api.GET('/api/v2/schedules/list'));
			const artById = new Map(
				this.screenings.map((s) => [s.id, { feature: s.feature, features: s.features }])
			);
			const fresh: KioskScreening[] = (data.schedules ?? [])
				.filter((s) => s.end_time && ['scheduled', 'running'].includes(s.status))
				.map((s) => ({
					id: s.id,
					programme: s.programme.name,
					start: s.play_time, // the showtime, not the lead-in
					end: s.end_time!,
					runtime: s.runtime,
					status: s.status,
					// Poster art comes from the display payload; keep what we have, fill in on the next refresh.
					feature: artById.get(s.id)?.feature ?? null,
					features: artById.get(s.id)?.features ?? []
				}));
			const sig = (list: KioskScreening[]) =>
				JSON.stringify(list.map((s) => [s.id, s.start, s.status]));
			if (sig(fresh) !== sig(this.screenings)) this.screenings = fresh;
			// Auto layout re-evaluates here (per poll, never per tick).
			this.autoChoice = this.#resolveAutoChoice();
		} catch {
			// Silent: the next poll self-heals.
		}
	}

	// Pick the base layout by how imminent the schedule is: split when close, wall further out, spotlight when nothing is booked.
	#resolveAutoChoice(): string {
		const screenings = this.activeScreenings;
		if (!screenings.length) return 'spotlight';
		const next = screenings[0];
		if (isRunning(next, this.now) || Date.parse(next.start) - this.now <= AUTO_SPLIT_MS)
			return 'split';
		return 'wall';
	}

	/** One-shot fetch of the playout status for the first paint; the socket drives updates after. */
	async #pollPlayout(): Promise<void> {
		try {
			const data = await unwrap(api.GET('/api/v2/playout/status'));
			this.#adoptPlayoutStatus(data);
		} catch {
			this.playout = null;
		}
	}

	/** Normalise the status payload down to what the takeover renders. */
	#adoptPlayoutStatus(data: PlayoutStatus | null | undefined): void {
		// The takeover shows while a programme has started (the server's phase), paused included.
		const prog = data?.programme;
		if (!data || !prog || !started(data)) {
			this.playout = null;
			return;
		}
		const playlist = data.playlist;
		this.playout = {
			programmeName: prog.name,
			phase: data.phase,
			paused: data.phase === 'paused',
			features: (prog.features || []).map((f) => ({
				id: f.id,
				title: f.title,
				year: f.year ?? null,
				cert: f.certification || '',
				runtime: f.runtime_minutes || 0,
				poster: f.thumbnail_url ?? null
			})),
			programmeDuration: Number(playlist?.programme_total_duration) || 0,
			programmeElapsed: Number(playlist?.programme_elapsed_time) || 0,
			programmeRemaining: Number(playlist?.programme_remaining_time) || 0,
			fetchedAt: Date.now()
		};
	}

	/** Every feature of a screening (older payloads only carry the first). */
	screeningFeatures(screening: KioskScreening): KioskFilm[] {
		if (screening.features?.length) return screening.features;
		return screening.feature ? [screening.feature] : [];
	}

	/** A screening's bill: its features, the headline and the line beneath it. */
	bill(s: KioskScreening | null) {
		const feats = s ? this.screeningFeatures(s) : [];
		const single = feats.length === 1 ? feats[0] : null;
		const title = single ? single.title : (s?.programme ?? '');
		let sub = '';
		if (single) sub = single.title !== s?.programme ? (s?.programme ?? '') : '';
		else if (feats.length > 1) sub = feats.map((f) => f.title).join('  +  ');
		return { feats, single, title, sub };
	}

	/** The next screening whose bill includes this film (for showtime lines). */
	showtimeFor(film: KioskFilm): KioskScreening | null {
		return (
			this.activeScreenings.find((s) => this.screeningFeatures(s).some((f) => f.id === film.id)) ||
			null
		);
	}

	/** Every film on the upcoming bills, soonest first, de-duplicated. */
	screeningFilms(): KioskFilm[] {
		const films = new Map<number, KioskFilm>();
		for (const s of this.activeScreenings)
			for (const f of this.screeningFeatures(s)) if (!films.has(f.id)) films.set(f.id, f);
		return [...films.values()];
	}

	/** The bill the takeover shows: the payload's features, else display art. */
	takeoverFilms(p: KioskPlayout): KioskFilmish[] {
		if (p.features.length) {
			// Prefer the display payload's richer art, keeping the payload's order.
			return p.features.map((f) => this.films.find((k) => k.id === f.id) || f);
		}
		const screening = this.activeScreenings.find((s) => s.programme === p.programmeName);
		return screening ? this.screeningFeatures(screening) : [];
	}

	/** Programme elapsed corrected for poll staleness (frozen while paused, and once nothing
	 *  has been heard for a while: Cinefin may be gone, and the film with it). */
	programmeElapsedNow(p: KioskPlayout): number {
		const elapsed = p.paused ? p.programmeElapsed : p.programmeElapsed + this.#sinceFetch(p);
		return p.programmeDuration > 0 ? Math.min(elapsed, p.programmeDuration) : elapsed;
	}

	/** The progress readout — always the programme-wide clock. */
	playoutEndsText(p: KioskPlayout): string {
		if (p.phase === 'preshow') return 'Starting shortly';
		if (p.paused) return 'Paused';
		const left =
			p.programmeDuration > 0
				? Math.max(0, p.programmeDuration - this.programmeElapsedNow(p))
				: Math.max(0, p.programmeRemaining - this.#sinceFetch(p));
		if (left <= 0) return '';
		return `Ends ~${fmtClock(new Date(this.now + left * 1000))}`;
	}

	/** Seconds since the playout status arrived, counting no further than EXTRAPOLATE_S. */
	#sinceFetch(p: KioskPlayout): number {
		return Math.min(this.now - p.fetchedAt, EXTRAPOLATE_S * 1000) / 1000;
	}

	countdownClock(screening: KioskScreening): string {
		return countdownClockText(screening, this.now);
	}

	// Night hours deliberately KEEP the lock: night mode dims via CSS so a live playout can wake it instantly — a released lock lets the OS blank the panel, which CSS can't wake.
	#wakeLock: WakeLockSentinel | null = null;

	async #acquireWakeLock(): Promise<void> {
		if (!('wakeLock' in navigator) || document.visibilityState !== 'visible') return;
		try {
			this.#wakeLock = await navigator.wakeLock.request('screen');
			this.#wakeLock.addEventListener('release', () => {
				this.#wakeLock = null;
			});
		} catch {
			this.#wakeLock = null; // denied (battery saver, policy) — skip silently
		}
	}

	#releaseWakeLock(): void {
		void this.#wakeLock?.release();
		this.#wakeLock = null;
	}

	#bindWakeLock(): void {
		if (!('wakeLock' in navigator)) return;
		const listen = (target: Document | Window, type: string, fn: () => void) => {
			target.addEventListener(type, fn);
			this.#stops.push(() => target.removeEventListener(type, fn));
		};
		// Hidden → the browser already released the lock; visible → retake it.
		listen(document, 'visibilitychange', () => {
			if (document.visibilityState === 'visible') void this.#acquireWakeLock();
		});
		listen(window, 'pagehide', () => this.#releaseWakeLock());
		listen(window, 'pageshow', () => void this.#acquireWakeLock());
		void this.#acquireWakeLock();
	}
}
