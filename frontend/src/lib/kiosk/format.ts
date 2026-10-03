import type { KioskFilm } from './kiosk.svelte';

export function clock(d: Date | string | number, h12 = false): string {
	return new Date(d).toLocaleTimeString(h12 ? 'en-US' : 'en-GB', {
		hour: h12 ? 'numeric' : '2-digit',
		minute: '2-digit',
		hour12: h12
	});
}

/** "Tonight", "Today", "Tomorrow", "Saturday", then "Sat 11 Oct" beyond the week. */
export function day(d: Date | string | number, now: number): string {
	const date = new Date(d);
	const midnight = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
	const days = Math.round((midnight(date) - midnight(new Date(now))) / 86_400_000);
	if (days === 0) return date.getHours() >= 17 ? 'Tonight' : 'Today';
	if (days === 1) return 'Tomorrow';
	if (days < 7) return date.toLocaleDateString('en-GB', { weekday: 'long' });
	return date.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
}

export function runtime(minutes: number | null | undefined): string {
	if (!minutes) return '';
	const h = Math.floor(minutes / 60);
	const m = Math.round(minutes % 60);
	return h ? (m ? `${h}h ${m}m` : `${h}h`) : `${m}m`;
}

/** "2021 · 15 · 1h 39m", skipping what's unknown. */
export function facts(film: Partial<KioskFilm>, cert = true): string {
	return [film.year, cert && film.cert, runtime(film.runtime)].filter(Boolean).join(' · ');
}

/** "tonight", "tomorrow", "Saturday": a day inside a sentence. */
export function dayIn(d: Date | string | number, now: number): string {
	const word = day(d, now);
	return ['Tonight', 'Today', 'Tomorrow'].includes(word) ? word.toLowerCase() : word;
}

/** A long name set smaller, so it stays on two lines. */
export function fit(name: string, px: number): number {
	return Math.round(name.length > 30 ? px * 0.62 : name.length > 18 ? px * 0.8 : px);
}
