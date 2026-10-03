// SettingsStore: the Settings page's draft of the main and trailer settings. The page saves it a
// moment after each change (AutoSave); a save sends only what changed since the last one, and
// can be undone. Numeric inputs are held as strings.
import { api, unwrap, ApiError, toApiError } from '$lib/api/client';
import { mutate } from '$lib/api/mutate';
import { unwrapLoose } from '$lib/jobs';
import { showToast } from '$lib/toast.svelte';
import type { components } from '$lib/api/types.gen';
import type { CheckState } from './types';

/** The built-in accent — the mark's blue channel. Keep in step with --color-accent in app.css. */
export const DEFAULT_ACCENT = '#3a7bff';

export interface Bumper {
	id: number;
	title: string;
	duration: number;
	/** As the ident: where standby freezes, in seconds; null = its last frame. */
	hold_point?: number | null;
}

/** The draft of the saved settings. Keys match the backend payload field names so field-level
 *  save errors map 1:1. */
function mainDraft(s: components['schemas']['SettingsDataSchema']) {
	return {
		cinema_name: s.cinema_name,
		ratings_system: s.ratings_system ?? 'BBFC',
		default_cinema_ident:
			s.default_cinema_ident_id != null ? String(s.default_cinema_ident_id) : '',
		ticket_total_rows: String(s.ticket_total_rows),
		ticket_seats_per_row: String(s.ticket_seats_per_row),
		ticket_printer_type: (s.ticket_printer_type === 'network' ? 'network' : 'file') as string,
		ticket_printer_device: s.ticket_printer_device,
		ticket_printer_host: s.ticket_printer_host ?? '',
		ticket_printer_port: String(s.ticket_printer_port ?? 9100),
		ticket_printer_timeout: String(s.ticket_printer_timeout ?? 30),
		ticket_feed_lines: String(s.ticket_feed_lines ?? 2),
		ticket_cut: s.ticket_cut || 'off',
		ticket_image_mode: s.ticket_image_mode || 'raster',
		ticket_paper_width: (s.ticket_paper_width === 576 ? '576' : '384') as string,
		subtitle_font_size: String(s.subtitle_font_size ?? 55),
		subtitle_color: s.subtitle_color || '#FFFFFF',
		subtitle_border_style: s.subtitle_border_style || 'outline-and-shadow',
		subtitle_back_color: s.subtitle_back_color || '#000000',
		subtitle_position: String(s.subtitle_position ?? 100),
		subtitle_margin_y: String(s.subtitle_margin_y ?? 22),
		subtitle_use_margins: !!s.subtitle_use_margins,
		subtitle_bold: !!s.subtitle_bold,
		playout_server_url: s.playout_server_url ?? '',
		accent_color: s.accent_color || DEFAULT_ACCENT,
		display_time_format: (s.display_time_format === '12h' ? '12h' : '24h') as string,
		kiosk_between: s.kiosk_between ?? 'whats_on',
		kiosk_rotate_seconds: String(s.kiosk_rotate_seconds ?? 15),
		kiosk_doors_minutes: String(s.kiosk_doors_minutes ?? 30),
		kiosk_clock: !!s.kiosk_clock,
		kiosk_night: !!s.kiosk_night,
		kiosk_night_start: s.kiosk_night_start ?? '01:00',
		kiosk_night_end: s.kiosk_night_end ?? '08:00',
		kiosk_content_source: s.kiosk_content_source ?? 'flagged'
	};
}
export type MainDraft = ReturnType<typeof mainDraft>;

function trailerDraft(t: components['schemas']['TrailerSettingsSchema']) {
	return {
		tmdb_api_key: t.tmdb_api_key || '',
		download_quality: t.download_quality || '1080',
		upcoming_months_ahead: String(t.upcoming_months_ahead ?? 6),
		filename_template: t.filename_template || '',
		folder_template: t.folder_template || '',
		rating_lookup_enabled: t.rating_lookup_enabled !== false
	};
}

/** Which nav section a save-rejected field lives in (to reveal it). */
function sectionOf(field: string): string | undefined {
	const named: Record<string, string> = {
		cinema_name: 'cinema',
		ratings_system: 'cinema',
		default_cinema_ident: 'playout',
		playout_server_url: 'playout',
		accent_color: 'appearance',
		display_time_format: 'appearance'
	};
	const byPrefix: Record<string, string> = {
		kiosk: 'kiosk',
		ticket: 'tickets',
		subtitle: 'playout'
	};
	return named[field] ?? byPrefix[field.split('_')[0]];
}

export type SaveResult =
	{ ok: true } | { ok: false; message: string; field?: string; section?: string };

export class SettingsStore {
	loading = $state(true);
	error = $state<ApiError | null>(null);

	// Filled by load(); the page renders no section before it succeeds.
	main = $state<MainDraft>({} as MainDraft);
	// Kept when the trailer settings can't be read.
	trailers = $state(trailerDraft({}));
	/** True when no custom accent is saved or picked ('' saves = reset). */
	accentCleared = $state(false);

	bumpers = $state<Bumper[]>([]);
	webLogoUrl = $state<string | null>(null);
	updatedAt = $state('');
	saving = $state(false);
	/** Field rejected by the last save, for the inline highlight. */
	fieldError = $state<{ field: string; message: string } | null>(null);

	#baseline = $state<string | null>(null);
	/** The draft before the last save, for Undo; dropped by the next edit's save. */
	#undo = $state<string | null>(null);
	/** The next save puts back an undone change: it is not itself undoable. */
	#undoing = false;
	/** Fields the last save wrote, for their "Saved" mark. */
	savedKeys = $state<string[]>([]);

	/** The whole draft as one string: an effect reading it reruns on any change. */
	get signature(): string {
		return JSON.stringify({ m: this.main, t: this.trailers, a: this.accentCleared });
	}

	snapshot(): void {
		this.#baseline = this.signature;
	}

	get canUndo(): boolean {
		return this.#undo !== null && !this.dirtyCount;
	}

	/** Put back what the last save changed; the page's autosave then saves that. */
	undo(): void {
		if (!this.#undo) return;
		const was = JSON.parse(this.#undo);
		this.#undo = null;
		this.#undoing = true;
		this.main = was.m;
		this.trailers = was.t;
		this.accentCleared = was.a;
	}

	isSaved(key: string): boolean {
		return this.savedKeys.includes(key) && !this.isDirty(key);
	}

	get dirtyKeys(): string[] {
		if (!this.#baseline) return [];
		const base = JSON.parse(this.#baseline);
		const changed = (now: object, was: Record<string, unknown>, prefix = '') =>
			Object.entries(now)
				.filter(([k, v]) => JSON.stringify(v) !== JSON.stringify(was[k]))
				.map(([k]) => prefix + k);
		const keys = [...changed(this.main, base.m), ...changed(this.trailers, base.t, 'trailers.')];
		if (this.accentCleared !== base.a && !keys.includes('accent_color')) keys.push('accent_color');
		return keys;
	}

	get dirtyCount(): number {
		return this.dirtyKeys.length;
	}

	isDirty(key: string): boolean {
		return this.dirtyKeys.includes(key);
	}

	/** Save-rejection message for a field, to show inline next to it. */
	errorFor(field: string): string | null {
		return this.fieldError?.field === field ? this.fieldError.message : null;
	}

	async load(): Promise<void> {
		this.loading = true;
		this.error = null;
		try {
			const [data, trailerData] = await Promise.all([
				unwrap(api.GET('/api/v2/settings/')),
				unwrapLoose<{ settings?: components['schemas']['TrailerSettingsSchema'] }>(
					api.GET('/api/v2/trailers/settings')
				).catch(() => null)
			]);
			const s = data.settings;
			this.bumpers = data.bumpers;
			this.webLogoUrl = s.cinema_web_logo_url ?? null;
			this.updatedAt = s.updated_at;
			this.accentCleared = !s.accent_color;
			this.main = mainDraft(s);
			if (trailerData) this.trailers = trailerDraft(trailerData.settings ?? {});
			this.fieldError = null;
			this.#undo = null;
			this.savedKeys = [];
			this.snapshot();
		} catch (e) {
			this.error = toApiError(e);
		} finally {
			this.loading = false;
		}
	}

	async save(): Promise<SaveResult> {
		const keys = this.dirtyKeys;
		if (!keys.length) return { ok: true };
		this.saving = true;
		this.fieldError = null;
		// What this save sends: edits made while it runs stay dirty and save next.
		const sent = this.signature;
		const before = this.#baseline;
		const mainChanged = keys.some((k) => !k.startsWith('trailers.'));
		const trailersChanged = keys.some((k) => k.startsWith('trailers.'));
		const m = this.main;
		const int = (v: string, fallback: number) => parseInt(v, 10) || fallback;
		const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
		try {
			if (mainChanged)
				await mutate(
					api.POST('/api/v2/settings/', {
						body: {
							cinema_name: m.cinema_name.trim(),
							ratings_system: m.ratings_system,
							// null (sent, not omitted) = the System Ident; the server clears its saved id.
							default_cinema_ident: m.default_cinema_ident
								? parseInt(m.default_cinema_ident, 10)
								: null,
							ticket_total_rows: int(m.ticket_total_rows, 1),
							ticket_seats_per_row: int(m.ticket_seats_per_row, 1),
							ticket_printer_type: m.ticket_printer_type,
							ticket_printer_device: m.ticket_printer_device.trim(),
							ticket_printer_host: m.ticket_printer_host.trim(),
							ticket_printer_port: int(m.ticket_printer_port, 9100),
							ticket_printer_timeout: int(m.ticket_printer_timeout, 30),
							ticket_feed_lines: clamp(int(m.ticket_feed_lines, 0), 0, 20),
							ticket_cut: m.ticket_cut,
							ticket_image_mode: m.ticket_image_mode,
							ticket_paper_width: int(m.ticket_paper_width, 384),
							subtitle_font_size: int(m.subtitle_font_size, 55),
							subtitle_color: m.subtitle_color,
							subtitle_border_style: m.subtitle_border_style,
							subtitle_back_color: m.subtitle_back_color,
							subtitle_position: int(m.subtitle_position, 100),
							subtitle_margin_y: int(m.subtitle_margin_y, 22),
							subtitle_use_margins: m.subtitle_use_margins,
							subtitle_bold: m.subtitle_bold,
							playout_server_url: m.playout_server_url.trim(),
							// Empty string = reset to the built-in theme (server stores None).
							accent_color: this.accentCleared ? '' : m.accent_color,
							display_time_format: m.display_time_format,
							kiosk_between: m.kiosk_between,
							kiosk_rotate_seconds: clamp(int(m.kiosk_rotate_seconds, 15), 5, 300),
							kiosk_clock: m.kiosk_clock,
							kiosk_doors_minutes: clamp(int(m.kiosk_doors_minutes, 0), 0, 240),
							kiosk_night: m.kiosk_night,
							kiosk_night_start: m.kiosk_night_start || '01:00',
							kiosk_night_end: m.kiosk_night_end || '08:00',
							kiosk_content_source: m.kiosk_content_source
						}
					})
				);

			const t = this.trailers;
			if (trailersChanged)
				await mutate(
					api.POST('/api/v2/trailers/settings', {
						body: {
							tmdb_api_key: t.tmdb_api_key.trim() || null,
							download_quality: t.download_quality,
							rating_lookup_enabled: t.rating_lookup_enabled,
							upcoming_months_ahead: int(t.upcoming_months_ahead, 6),
							filename_template: t.filename_template.trim() || null,
							folder_template: t.folder_template.trim() || null
						}
					})
				);

			this.#baseline = sent;
			this.#undo = this.#undoing ? null : before;
			this.#undoing = false;
			this.savedKeys = keys;
			setTimeout(() => {
				if (this.savedKeys === keys) this.savedKeys = [];
			}, 3000);
			this.updatedAt = new Date().toISOString();
			return { ok: true };
		} catch (e) {
			const err = toApiError(e);
			const field = this.#fieldFromError(err);
			if (field) {
				this.fieldError = field;
				return {
					ok: false,
					message: field.message,
					field: field.field,
					section: sectionOf(field.field)
				};
			}
			return { ok: false, message: err.message || 'Failed to save settings' };
		} finally {
			this.saving = false;
		}
	}

	/** Pull { field, message } out of a failed save: our APIException envelope
	 * carries details.field; Ninja schema validation (422) carries a detail
	 * array whose loc ends with the field name. */
	#fieldFromError(err: ApiError): { field: string; message: string } | null {
		const details = err.details as Record<string, unknown> | null;
		if (details && typeof details.field === 'string') {
			return { field: details.field, message: err.message };
		}
		if (details && Array.isArray(details.detail) && details.detail.length) {
			const item = details.detail[0] as { loc?: unknown[]; msg?: string };
			const loc = Array.isArray(item.loc) ? item.loc : [];
			const field = loc.length ? String(loc[loc.length - 1]) : null;
			if (field) return { field, message: item.msg || 'Invalid value' };
		}
		return null;
	}
}

/** Django's date:"M j, Y H:i" (e.g. "Aug 15, 2026 14:03"), in local time. */
export function formatStamp(iso: string): string {
	const d = new Date(iso);
	if (Number.isNaN(d.getTime())) return '-';
	const pad = (n: number) => String(n).padStart(2, '0');
	return `${d.toLocaleString('en-US', { month: 'short' })} ${d.getDate()}, ${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** ISO → locale date-time, '—' for blank/invalid ('never' is the caller's call). */
export function formatDateTime(iso: string | null | undefined): string {
	if (!iso) return '-';
	const d = new Date(iso);
	return Number.isNaN(d.getTime()) ? '-' : d.toLocaleString();
}

export function formatBytes(bytes: number): string {
	if (!bytes) return '0 B';
	const units = ['B', 'KB', 'MB', 'GB'];
	let n = bytes;
	let i = 0;
	while (n >= 1024 && i < units.length - 1) {
		n /= 1024;
		i++;
	}
	return `${n.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

/**
 * unwrap() for endpoints that answer a bare schema with NO envelope (the
 * ticket-design CRUD and the /settings/test-* checks): resolves result.data
 * directly, throwing the same typed ApiError otherwise.
 */
export async function raw<T>(
	pending: PromiseLike<{ data?: T; error?: unknown; response: Response }>
): Promise<T> {
	const result = await pending;
	if (result.error !== undefined || result.data === undefined) {
		throw toApiError(result.error, result.response);
	}
	return result.data;
}

/** Run an action; on failure toast its message (else `fail`). Resolves whether it succeeded. */
export async function attempt(fn: () => Promise<unknown>, fail: string): Promise<boolean> {
	try {
		await fn();
		return true;
	} catch (e) {
		showToast(errorText(e, fail), 'error');
		return false;
	}
}

export const errorText = (e: unknown, fallback: string) =>
	(e instanceof Error && e.message) || fallback;

/** Run a check endpoint ({ ok, message }) and read its answer as a CheckState. */
export async function runCheck(
	fn: () => Promise<{ ok: boolean; message: string }>
): Promise<CheckState> {
	try {
		const res = await fn();
		return { state: res.ok ? 'ok' : 'error', message: res.message };
	} catch (e) {
		return { state: 'error', message: errorText(e, 'Test failed') };
	}
}
