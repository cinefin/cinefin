// SettingsStore — the Settings page's single source of truth.
//
// One sticky "Save changes" writes the main settings then the trailer settings.
// Everything else (security, API keys, playout hosts, rating cards, web logo,
// ticket designs) applies immediately and is NOT part of the draft/dirty tracking.
// Numeric inputs are held as strings (what the <input>s bind) and parsed on save.
import { api, unwrap, ApiError, toApiError } from '$lib/api/client';
import { mutate } from '$lib/api/mutate';
import { unwrapLoose } from '$lib/jobs';
import type { TrailerSettingsData } from './types';

/** The built-in accent — the mark's blue channel. Keep in step with --color-accent in app.css. */
export const DEFAULT_ACCENT = '#3a7bff';

export interface Bumper {
	id: number;
	title: string;
	duration: number;
}

export interface CommandRef {
	id: number;
	name: string;
}

/** Keys match the backend payload field names so field-level save errors map 1:1. */
export interface MainDraft {
	cinema_name: string;
	ratings_system: string;
	default_cinema_ident: string; // bumper id or '' = none
	ticket_total_rows: string;
	ticket_seats_per_row: string;
	ticket_printer_type: string;
	ticket_printer_device: string;
	ticket_printer_host: string;
	ticket_printer_port: string;
	ticket_printer_timeout: string;
	ticket_feed_lines: string;
	ticket_image_mode: string;
	ticket_qr_fun_links: string[];
	ticket_paper_width: string;
	ticket_date_format: string;
	ticket_time_format: string;
	subtitle_font_size: string;
	subtitle_color: string;
	subtitle_border_style: string;
	subtitle_back_color: string;
	subtitle_position: string;
	subtitle_margin_y: string;
	subtitle_use_margins: boolean;
	subtitle_bold: boolean;
	playout_server_url: string;
	preshow_commands: number[];
	accent_color: string;
	display_time_format: string;
	kiosk_layout: string;
	kiosk_rotate_minutes: string;
	kiosk_countdown_minutes: string;
	kiosk_header: boolean;
	kiosk_clock: boolean;
	kiosk_takeover: boolean;
	kiosk_night: boolean;
	kiosk_night_start: string;
	kiosk_night_end: string;
	kiosk_content_source: string;
	kiosk_show_showtimes: boolean;
}

export interface TrailerDraft {
	tmdb_api_key: string;
	download_quality: string;
	upcoming_months_ahead: string;
	filename_template: string;
	folder_template: string;
	rating_lookup_enabled: boolean;
}

/** Which nav section a save-rejected field lives in (to reveal it). */
const FIELD_SECTIONS: Record<string, string> = {
	cinema_name: 'cinema',
	ratings_system: 'cinema',
	default_cinema_ident: 'playout',
	subtitle_font_size: 'playout',
	subtitle_color: 'playout',
	subtitle_border_style: 'playout',
	subtitle_back_color: 'playout',
	subtitle_position: 'playout',
	subtitle_margin_y: 'playout',
	playout_server_url: 'playout',
	preshow_commands: 'playout',
	accent_color: 'appearance',
	display_time_format: 'appearance'
};

function emptyMain(): MainDraft {
	return {
		cinema_name: '',
		ratings_system: 'BBFC',
		default_cinema_ident: '',
		ticket_total_rows: '10',
		ticket_seats_per_row: '20',
		ticket_printer_type: 'file',
		ticket_printer_device: '',
		ticket_printer_host: '',
		ticket_printer_port: '9100',
		ticket_printer_timeout: '30',
		ticket_feed_lines: '2',
		ticket_image_mode: 'raster',
		ticket_qr_fun_links: [],
		ticket_paper_width: '384',
		ticket_date_format: '%d/%m/%Y',
		ticket_time_format: '%H:%M',
		subtitle_font_size: '55',
		subtitle_color: '#FFFFFF',
		subtitle_border_style: 'outline-and-shadow',
		subtitle_back_color: '#000000',
		subtitle_position: '100',
		subtitle_margin_y: '22',
		subtitle_use_margins: true,
		subtitle_bold: false,
		playout_server_url: '',
		preshow_commands: [],
		accent_color: DEFAULT_ACCENT,
		display_time_format: '24h',
		kiosk_layout: 'wall',
		kiosk_rotate_minutes: '0',
		kiosk_countdown_minutes: '30',
		kiosk_header: true,
		kiosk_clock: true,
		kiosk_takeover: true,
		kiosk_night: false,
		kiosk_night_start: '01:00',
		kiosk_night_end: '08:00',
		kiosk_content_source: 'flagged',
		kiosk_show_showtimes: true
	};
}

function emptyTrailers(): TrailerDraft {
	return {
		tmdb_api_key: '',
		download_quality: '1080',
		upcoming_months_ahead: '6',
		filename_template: '',
		folder_template: '',
		rating_lookup_enabled: true
	};
}

export type SaveResult =
	{ ok: true } | { ok: false; message: string; field?: string; section?: string };

export class SettingsStore {
	loading = $state(true);
	error = $state<ApiError | null>(null);

	main = $state<MainDraft>(emptyMain());
	trailers = $state<TrailerDraft>(emptyTrailers());
	/** True when no custom accent is saved or picked ('' saves = reset). */
	accentCleared = $state(false);

	bumpers = $state<Bumper[]>([]);
	commands = $state<CommandRef[]>([]);
	namingTokens = $state<{ token: string; description: string }[]>([]);
	webLogoUrl = $state<string | null>(null);
	updatedAt = $state('');
	saving = $state(false);
	/** Field rejected by the last save, for the inline highlight. */
	fieldError = $state<{ field: string; message: string } | null>(null);

	#baseline = $state<string | null>(null);

	commandName(id: number): string {
		return this.commands.find((c) => c.id === id)?.name ?? `Command #${id}`;
	}

	snapshot(): void {
		this.#baseline = JSON.stringify({
			m: this.main,
			t: this.trailers,
			a: this.accentCleared
		});
	}

	get dirtyKeys(): string[] {
		if (!this.#baseline) return [];
		const base = JSON.parse(this.#baseline) as {
			m: Record<string, unknown>;
			t: Record<string, unknown>;
			a: boolean;
		};
		const keys: string[] = [];
		for (const [k, v] of Object.entries(this.main)) {
			if (JSON.stringify(v) !== JSON.stringify(base.m[k])) keys.push(k);
		}
		for (const [k, v] of Object.entries(this.trailers)) {
			if (JSON.stringify(v) !== JSON.stringify(base.t[k])) keys.push(`trailers.${k}`);
		}
		if (this.accentCleared !== base.a && !keys.includes('accent_color')) {
			keys.push('accent_color');
		}
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
			const [data, commands, trailerData] = await Promise.all([
				unwrap(api.GET('/api/v2/settings/')),
				// Command names are garnish for the pre-show picker — degrade quietly.
				unwrap(api.GET('/api/v2/commands/list')).then(
					(d) => d.commands.map((c) => ({ id: c.id, name: c.name })),
					() => [] as CommandRef[]
				),
				unwrapLoose<TrailerSettingsData>(api.GET('/api/v2/trailers/settings')).catch(() => null)
			]);
			const s = data.settings;
			this.bumpers = data.bumpers;
			this.commands = commands;
			this.webLogoUrl = s.cinema_web_logo_url ?? null;
			this.updatedAt = s.updated_at;
			this.accentCleared = !s.accent_color;
			this.main = {
				cinema_name: s.cinema_name,
				ratings_system: s.ratings_system ?? 'BBFC',
				default_cinema_ident:
					s.default_cinema_ident_id != null ? String(s.default_cinema_ident_id) : '',
				ticket_total_rows: String(s.ticket_total_rows),
				ticket_seats_per_row: String(s.ticket_seats_per_row),
				ticket_printer_type: s.ticket_printer_type === 'network' ? 'network' : 'file',
				ticket_printer_device: s.ticket_printer_device,
				ticket_printer_host: s.ticket_printer_host ?? '',
				ticket_printer_port: String(s.ticket_printer_port ?? 9100),
				ticket_printer_timeout: String(s.ticket_printer_timeout ?? 30),
				ticket_feed_lines: String(s.ticket_feed_lines ?? 2),
				ticket_image_mode: s.ticket_image_mode || 'raster',
				ticket_qr_fun_links: (s.ticket_qr_fun_links ?? []).slice(),
				ticket_paper_width: s.ticket_paper_width === 576 ? '576' : '384',
				ticket_date_format: s.ticket_date_format ?? '%d/%m/%Y',
				ticket_time_format: s.ticket_time_format ?? '%H:%M',
				subtitle_font_size: String(s.subtitle_font_size ?? 55),
				subtitle_color: s.subtitle_color || '#FFFFFF',
				subtitle_border_style: s.subtitle_border_style || 'outline-and-shadow',
				subtitle_back_color: s.subtitle_back_color || '#000000',
				subtitle_position: String(s.subtitle_position ?? 100),
				subtitle_margin_y: String(s.subtitle_margin_y ?? 22),
				subtitle_use_margins: !!s.subtitle_use_margins,
				subtitle_bold: !!s.subtitle_bold,
				playout_server_url: s.playout_server_url ?? '',
				preshow_commands: (s.preshow_commands ?? []).slice(),
				accent_color: s.accent_color || DEFAULT_ACCENT,
				display_time_format: s.display_time_format === '12h' ? '12h' : '24h',
				kiosk_layout: s.kiosk_layout ?? 'wall',
				kiosk_rotate_minutes: String(s.kiosk_rotate_minutes ?? 0),
				kiosk_countdown_minutes: String(s.kiosk_countdown_minutes ?? 30),
				kiosk_header: !!s.kiosk_header,
				kiosk_clock: !!s.kiosk_clock,
				kiosk_takeover: !!s.kiosk_takeover,
				kiosk_night: !!s.kiosk_night,
				kiosk_night_start: s.kiosk_night_start ?? '01:00',
				kiosk_night_end: s.kiosk_night_end ?? '08:00',
				kiosk_content_source: s.kiosk_content_source ?? 'flagged',
				kiosk_show_showtimes: !!s.kiosk_show_showtimes
			};
			if (trailerData) {
				const t = trailerData.settings ?? {};
				this.namingTokens = trailerData.naming_tokens ?? [];
				this.trailers = {
					tmdb_api_key: t.tmdb_api_key || '',
					download_quality: t.download_quality || '1080',
					upcoming_months_ahead: String(t.upcoming_months_ahead ?? 6),
					filename_template: t.filename_template || '',
					folder_template: t.folder_template || '',
					rating_lookup_enabled: t.rating_lookup_enabled !== false
				};
			}
			this.fieldError = null;
			this.snapshot();
		} catch (e) {
			this.error = toApiError(e);
		} finally {
			this.loading = false;
		}
	}

	async save(): Promise<SaveResult> {
		this.saving = true;
		this.fieldError = null;
		const m = this.main;
		const int = (v: string, fallback: number) => parseInt(v, 10) || fallback;
		const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
		try {
			await mutate(
				api.POST('/api/v2/settings/', {
					body: {
						cinema_name: m.cinema_name.trim(),
						ratings_system: m.ratings_system,
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
						ticket_image_mode: m.ticket_image_mode,
						ticket_qr_fun_links: m.ticket_qr_fun_links.map((l) => l.trim()).filter(Boolean),
						ticket_paper_width: int(m.ticket_paper_width, 384),
						ticket_date_format: m.ticket_date_format,
						ticket_time_format: m.ticket_time_format,
						subtitle_font_size: int(m.subtitle_font_size, 55),
						subtitle_color: m.subtitle_color,
						subtitle_border_style: m.subtitle_border_style,
						subtitle_back_color: m.subtitle_back_color,
						subtitle_position: int(m.subtitle_position, 100),
						subtitle_margin_y: int(m.subtitle_margin_y, 22),
						subtitle_use_margins: m.subtitle_use_margins,
						subtitle_bold: m.subtitle_bold,
						playout_server_url: m.playout_server_url.trim(),
						preshow_commands: m.preshow_commands,
						// Empty string = reset to the built-in theme (server stores None).
						accent_color: this.accentCleared ? '' : m.accent_color,
						display_time_format: m.display_time_format,
						kiosk_layout: m.kiosk_layout,
						kiosk_rotate_minutes: int(m.kiosk_rotate_minutes, 0),
						kiosk_header: m.kiosk_header,
						kiosk_clock: m.kiosk_clock,
						kiosk_takeover: m.kiosk_takeover,
						kiosk_countdown_minutes: clamp(int(m.kiosk_countdown_minutes, 0), 0, 480),
						kiosk_night: m.kiosk_night,
						kiosk_night_start: m.kiosk_night_start || '01:00',
						kiosk_night_end: m.kiosk_night_end || '08:00',
						kiosk_content_source: m.kiosk_content_source,
						kiosk_show_showtimes: m.kiosk_show_showtimes
					}
				})
			);

			const t = this.trailers;
			await api.POST('/api/v2/trailers/settings', {
				body: {
					tmdb_api_key: t.tmdb_api_key.trim() || null,
					download_quality: t.download_quality,
					rating_lookup_enabled: t.rating_lookup_enabled,
					upcoming_months_ahead: int(t.upcoming_months_ahead, 6),
					filename_template: t.filename_template.trim() || null,
					folder_template: t.folder_template.trim() || null
				}
			});

			this.snapshot();
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
					section: FIELD_SECTIONS[field.field] ?? this.#sectionFromPrefix(field.field)
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

	#sectionFromPrefix(field: string): string | undefined {
		if (field.startsWith('kiosk_')) return 'kiosk';
		if (field.startsWith('ticket_')) return 'tickets';
		if (field.startsWith('subtitle_')) return 'playout';
		return undefined;
	}
}

/** Django's date:"M j, Y H:i" (e.g. "Aug 15, 2026 14:03"), in local time. */
export function formatStamp(iso: string): string {
	const d = new Date(iso);
	if (Number.isNaN(d.getTime())) return '-';
	const months = [
		'Jan',
		'Feb',
		'Mar',
		'Apr',
		'May',
		'Jun',
		'Jul',
		'Aug',
		'Sep',
		'Oct',
		'Nov',
		'Dec'
	];
	const pad = (n: number) => String(n).padStart(2, '0');
	return `${months[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
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
