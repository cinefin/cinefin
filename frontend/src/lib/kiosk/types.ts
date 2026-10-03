import type { components } from '$lib/api/types.gen';
import type { Phase } from '$lib/playout/phase';

export type KioskFilm = components['schemas']['KioskFilmSchema'];
export type KioskScreening = components['schemas']['KioskScreeningSchema'];
export type KioskSettings = components['schemas']['KioskDisplaySettingsSchema'];
export type KioskCinema = components['schemas']['KioskCinemaSchema'];
export type KioskDisplayData = components['schemas']['KioskDisplayDataSchema'];

export type KioskFilmish = Partial<KioskFilm>;

export interface KioskPlayout {
	programmeName: string;
	phase: Phase;
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
