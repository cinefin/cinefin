/** Shared display formatters. */

/** Seconds → "m:ss" or "h:mm:ss". */
export function formatTime(seconds: number): string {
	const s = Math.max(0, Math.floor(seconds));
	const h = Math.floor(s / 3600);
	const m = Math.floor((s % 3600) / 60);
	const sec = s % 60;
	const mm = h ? String(m).padStart(2, '0') : String(m);
	return `${h ? `${h}:` : ''}${mm}:${String(sec).padStart(2, '0')}`;
}

/** ISO date string → short relative age ("3 h ago", "2 d ago"). */
export function relativeTime(iso: string): string {
	const then = new Date(iso).getTime();
	if (Number.isNaN(then)) return '';
	const diff = Date.now() - then;
	const minutes = Math.round(diff / 60000);
	if (minutes < 1) return 'just now';
	if (minutes < 60) return `${minutes} min ago`;
	const hours = Math.round(minutes / 60);
	if (hours < 24) return `${hours} h ago`;
	const days = Math.round(hours / 24);
	if (days < 30) return `${days} d ago`;
	return new Date(iso).toLocaleDateString();
}

/** Date → "19:30". */
export function formatClock(d: Date): string {
	return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
}

/** Date → "Today" / "Tomorrow" / "12 Sep". */
export function dayLabel(d: Date): string {
	const today = new Date();
	today.setHours(0, 0, 0, 0);
	const that = new Date(d);
	that.setHours(0, 0, 0, 0);
	const diff = Math.round((that.getTime() - today.getTime()) / 86400000);
	if (diff === 0) return 'Today';
	if (diff === 1) return 'Tomorrow';
	return d.toLocaleDateString('en-GB', { month: 'short', day: 'numeric' });
}

/** Minutes → "2 h 15 min" (or "45 min"). */
export function formatRuntime(minutes: number): string {
	const m = Math.round(minutes);
	if (m < 60) return `${m} min`;
	const h = Math.floor(m / 60);
	const rest = m % 60;
	return rest ? `${h} h ${rest} min` : `${h} h`;
}
