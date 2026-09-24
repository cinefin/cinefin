import type { KioskScreening } from './types';

let use12h = false;

export function setClockFormat(format: string | undefined): void {
	use12h = format === '12h';
}

export function fmtClock(dateLike: Date | string | number): string {
	const d = dateLike instanceof Date ? dateLike : new Date(dateLike);
	if (isNaN(d.getTime())) return '';
	return d.toLocaleTimeString(use12h ? 'en-US' : 'en-GB', {
		hour: use12h ? 'numeric' : '2-digit',
		minute: '2-digit',
		hour12: use12h
	});
}

export function fmtRuntime(minutes: number | null | undefined): string {
	if (!minutes) return '';
	const m = Math.round(minutes);
	if (m < 60) return `${m}m`;
	const h = Math.floor(m / 60);
	const rest = m % 60;
	return rest ? `${h}h ${rest}m` : `${h}h`;
}

export function dayLabel(dateLike: Date | string | number): string {
	const d = new Date(dateLike);
	const now = new Date();
	const day = (x: Date) => `${x.getFullYear()}-${x.getMonth()}-${x.getDate()}`;
	if (day(d) === day(now)) return 'Today';
	const tomorrow = new Date(now.getTime() + 86400000);
	if (day(d) === day(tomorrow)) return 'Tomorrow';
	return d.toLocaleDateString('en-GB', { weekday: 'long' });
}

export function countdownText(screening: KioskScreening, now: number): string {
	const start = Date.parse(screening.start);
	const end = Date.parse(screening.end);
	if (start <= now && end > now) return `Ends ${fmtClock(new Date(end))}`;
	const day = dayLabel(start);
	if (day !== 'Today') return `Starts ${day === 'Tomorrow' ? 'tomorrow' : day}`;
	const mins = Math.max(0, Math.round((start - now) / 60000));
	if (mins < 1) return 'Starting now';
	if (mins < 60) return `Starts in ${mins} min`;
	const h = Math.floor(mins / 60);
	const m = mins % 60;
	return `Starts in ${h}h${m ? ` ${m}m` : ''}`;
}

// Minute granularity by design: a wall display counting seconds reads as urgent/anxious.
export function countdownClockText(screening: KioskScreening, now: number): string {
	const mins = Math.ceil((Date.parse(screening.start) - now) / 60000);
	if (mins <= 0) return 'Starting now';
	if (mins === 1) return '1 minute';
	if (mins < 60) return `${mins} minutes`;
	const h = Math.floor(mins / 60);
	const m = mins % 60;
	return `${h}h${m ? ` ${m}m` : ''}`;
}

export function isRunning(screening: KioskScreening, now: number): boolean {
	return Date.parse(screening.start) <= now && Date.parse(screening.end) > now;
}
