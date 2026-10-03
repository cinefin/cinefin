/**
 * The kiosk: three screens, picked by the clock and the player.
 * On air while a programme plays, Doors open shortly before a screening, else Between screenings.
 * A wall display never shows an error: a failed fetch keeps the last good state.
 */
import { api, unwrap } from '$lib/api/client';
import { onInvalidate } from '$lib/invalidate';
import { started, type PlayoutStatus } from '$lib/playout/phase';
import { screeningTitle } from '$lib/playout/screening-title';
import { realtime } from '$lib/realtime.svelte';
import type { components } from '$lib/api/types.gen';
import { clock, day, facts, runtime } from './format';

export type KioskFilm = components['schemas']['KioskFilmSchema'];
export type KioskScreening = components['schemas']['KioskScreeningSchema'];
type KioskData = components['schemas']['KioskDisplayDataSchema'];
export type Between = 'whats_on' | 'screenings' | 'films' | 'week';
export type Screen = 'on_air' | 'doors' | 'between' | 'night';

const BETWEEN: Between[] = ['whats_on', 'screenings', 'films', 'week'];
const RETRY_MS = 15_000;
const REFRESH_MS = 5 * 60_000;
const START_GRACE_MS = 90_000; // Doors open holds this long past the start for the player to begin

const minutes = (hhmm: string) => {
	const [h, m] = hhmm.split(':').map(Number);
	return (h || 0) * 60 + (m || 0);
};

export class Kiosk {
	data = $state<KioskData | null>(null);
	status = $state<PlayoutStatus | null>(null);
	now = $state(Date.now());
	/** Advances every rotate_seconds; the views that take turns show item `turn % length`. */
	turn = $state(0);

	#reloadKey = '';
	#stops: (() => void)[] = [];
	#retry: ReturnType<typeof setTimeout> | undefined;

	settings = $derived(this.data?.settings);
	cinema = $derived(this.data?.cinema);
	films = $derived(this.data?.films ?? []);

	/** Screenings not yet over, soonest first. */
	upcoming = $derived(
		(this.data?.screenings ?? [])
			.filter((s) => Date.parse(s.end) > this.now)
			.toSorted((a, b) => Date.parse(a.start) - Date.parse(b.start))
	);

	onAir = $derived(started(this.status) ? this.status : null);

	/** The screening Doors open is for. */
	doors = $derived.by(() => {
		const lead = (this.settings?.doors_minutes ?? 0) * 60_000;
		if (!lead || this.onAir) return null;
		return (
			this.upcoming.find((s) => {
				const start = Date.parse(s.start);
				return start - lead <= this.now && this.now < start + START_GRACE_MS;
			}) ?? null
		);
	});

	between = $derived.by((): Between => {
		const asked = new URLSearchParams(location.search).get('between') as Between;
		return BETWEEN.includes(asked) ? asked : ((this.settings?.between as Between) ?? 'whats_on');
	});

	night = $derived.by(() => {
		const s = this.settings;
		if (!s?.night) return false;
		const d = new Date(this.now);
		const cur = d.getHours() * 60 + d.getMinutes();
		const [from, to] = [minutes(s.night_start), minutes(s.night_end)];
		if (from === to) return false;
		return from < to ? cur >= from && cur < to : cur >= from || cur < to;
	});

	screen = $derived.by((): Screen => {
		if (this.onAir) return 'on_air';
		if (this.doors) return 'doors';
		return this.night ? 'night' : 'between';
	});

	start(): () => void {
		const tick = setInterval(() => (this.now = Date.now()), 1000);
		const refresh = setInterval(() => void this.#load(), REFRESH_MS);
		let rotate: ReturnType<typeof setInterval> | undefined;
		const rotation = $effect.root(() => {
			$effect(() => {
				const secs = Math.max(5, this.settings?.rotate_seconds ?? 15);
				clearInterval(rotate);
				rotate = setInterval(() => this.turn++, secs * 1000);
			});
		});
		this.#stops.push(
			() => clearInterval(tick),
			() => clearInterval(refresh),
			() => clearInterval(rotate),
			rotation,
			() => clearTimeout(this.#retry),
			realtime.subscribe({
				channel: 'playout',
				onMessage: (msg) => (this.status = msg.data as PlayoutStatus)
			}),
			onInvalidate(['schedules', 'settings', 'movies', 'deploy'], () => void this.#load()),
			this.#wakeLock()
		);
		void this.#load();
		unwrap(api.GET('/api/v2/playout/status')).then(
			(s) => (this.status = s),
			() => {}
		);
		return () => this.#stops.forEach((stop) => stop());
	}

	async #load(): Promise<void> {
		clearTimeout(this.#retry);
		try {
			const data = await unwrap(api.GET('/api/v2/kiosk/display'));
			// New code deployed: reload, but never in the middle of a screening.
			if (this.#reloadKey && data.reload_key !== this.#reloadKey && this.screen !== 'on_air') {
				location.reload();
				return;
			}
			this.#reloadKey ||= data.reload_key;
			this.data = data;
		} catch {
			if (!this.data) this.#retry = setTimeout(() => void this.#load(), RETRY_MS);
		}
	}

	/** The screen stays on: the lock is retaken whenever the page is shown again. */
	#wakeLock(): () => void {
		if (!('wakeLock' in navigator)) return () => {};
		let lock: WakeLockSentinel | null = null;
		const take = () => {
			if (document.visibilityState === 'visible')
				navigator.wakeLock.request('screen').then(
					(l) => (lock = l),
					() => {}
				);
		};
		document.addEventListener('visibilitychange', take);
		take();
		return () => {
			document.removeEventListener('visibilitychange', take);
			void lock?.release();
		};
	}

	/** A screening's films, enriched with the display payload's art and synopsis. */
	film(id: number): KioskFilm | undefined {
		return (
			this.films.find((f) => f.id === id) ??
			this.upcoming.flatMap((s) => s.features).find((f) => f.id === id)
		);
	}

	/** The next screening that shows this film. */
	showingOf(film: KioskFilm): KioskScreening | undefined {
		return this.upcoming.find((s) => s.features.some((f) => f.id === film.id));
	}

	/** Films to take turns with: the library's kiosk films, else those on upcoming screenings. */
	turnFilms = $derived.by(() => {
		if (this.films.length) return this.films;
		const seen = new Map<number, KioskFilm>();
		for (const s of this.upcoming)
			for (const f of s.features) if (!seen.has(f.id)) seen.set(f.id, f);
		return [...seen.values()];
	});

	pick<T>(list: T[]): T | undefined {
		return list.length ? list[this.turn % list.length] : undefined;
	}

	h12 = $derived(this.cinema?.time_format === '12h');

	time(d: string | number | Date): string {
		return clock(d, this.h12);
	}

	/** "Tonight 19:30", "Saturday 20:00". */
	when(s: KioskScreening): string {
		return `${day(s.start, this.now)} ${this.time(s.start)}`;
	}

	/** A screening's name and films, with the payload's fuller film records. */
	bill(s: KioskScreening) {
		return screeningTitle(
			s.programme,
			s.features.map((f) => this.film(f.id) ?? f)
		);
	}

	/** The line under a screening's name in a list: the film's facts, or its films and length. */
	line(s: KioskScreening, cert = true): { names: string; mono: string } {
		const b = this.bill(s);
		if (b.film) return { names: '', mono: facts(b.film, cert) };
		const one = b.films.length === 1 ? b.films[0] : null;
		const mono = one ? facts({ ...one, year: null }, cert) : runtime(s.runtime);
		return { names: b.films.map((f) => f.title).join(', '), mono };
	}
}
