import type { components } from '$lib/api/types.gen';
import type { PlayoutStatus } from '$lib/api/refinements';

export type KioskFilm = components['schemas']['KioskFilmSchema'];
export type KioskScreening = components['schemas']['KioskScreeningSchema'];
export type KioskSettings = components['schemas']['KioskDisplaySettingsSchema'];
export type KioskCinema = components['schemas']['KioskCinemaSchema'];
export type KioskDisplayData = components['schemas']['KioskDisplayDataSchema'];

export type KioskFilmish = Partial<KioskFilm>;

export interface KioskPlayoutFeature {
	id: number;
	title: string;
	year?: number | null;
	certification?: string | null;
	runtime_minutes?: number | null;
	thumbnail_url?: string | null;
}

export interface KioskPlayoutStatus extends PlayoutStatus {
	programme:
		| (NonNullable<PlayoutStatus['programme']> & { features?: KioskPlayoutFeature[] })
		| null;
	playlist?:
		| (NonNullable<PlayoutStatus['playlist']> & {
				programme_total_duration?: number;
				programme_elapsed_time?: number;
				programme_remaining_time?: number;
		  })
		| null;
}

export interface KioskPlayout {
	programmeName: string;
	programmeState: string;
	paused: boolean;
	features: KioskFilmish[];
	programmeDuration: number;
	programmeElapsed: number;
	programmeRemaining: number;
	fetchedAt: number;
}

/** Resolved display preferences (defaults < server < overrides < URL). */
export interface KioskPrefs {
	layout: string;
	rotate: number; // cycle ambient layouts every N minutes (0 = off)
	clock: boolean;
	header: boolean;
	takeover: boolean;
	countdown: number;
	night: boolean;
	nightStart: string;
	nightEnd: string;
	spotlightSecs: number;
	wallPageSecs: number;
	showtimes: boolean;
}

export type KioskMode = 'playout' | 'countdown' | 'night' | 'layout';
