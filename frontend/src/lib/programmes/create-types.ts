import { itemTypeCount } from '$lib/item-types';
import { runtimeRange, yearRange } from '$lib/editor/types';
import type { components } from '$lib/api/types.gen';
import type { ProgrammeItemIn } from '$lib/editor/programme-adapter';

export type AudioTrack = components['schemas']['AudioTrackSchema'];
export type SubtitleTrack = components['schemas']['SubtitleTrackSchema'];
export type TemplateSummary = components['schemas']['TemplateSummarySchema'];

export interface SelectedFilm {
	kind: 'movie';
	id: number;
	title: string;
	year: number | null;
	runtime: number | null;
	certification: string | null;
	thumbnail_url: string | null;
	director: string | null;
	description: string | null;
	genre_ids: number[];
	resolution: string | null;
	video_codec: string | null;
	audio_tracks: AudioTrack[];
	subtitle_tracks: SubtitleTrack[];
	audio_track_index: number;
	subtitle_track_index: number | null;
}

export interface RandomSlot {
	kind: 'random';
	id: number;
	label: string | null;
	genre_ids: number[];
	genre_names: string[];
	certification: string | null;
	year_from: number | null;
	year_to: number | null;
	runtime_from: number | null;
	runtime_to: number | null;
}

export type SelectedItem = SelectedFilm | RandomSlot;

export function itemTitle(item: SelectedItem): string {
	return item.kind === 'movie' ? item.title : item.label || 'Random movie';
}

export function slotFilterText(slot: RandomSlot): string {
	const g = slot.genre_names;
	const genres = g.length <= 2 ? g.join(', ') : `${g[0]} +${g.length - 1} more`;
	const text = [
		genres,
		slot.certification,
		yearRange(slot.year_from, slot.year_to),
		runtimeRange(slot.runtime_from, slot.runtime_to)
	]
		.filter(Boolean)
		.join(' · ');
	return text || 'Any movie';
}

export function templateBreakdown(template: TemplateSummary): string {
	const counts = new Map<string, number>();
	for (const t of template.item_types ?? []) counts.set(t, (counts.get(t) || 0) + 1);
	if (!counts.size) return `${template.items_count || 0} items`;
	const parts: string[] = [];
	for (const [type, n] of counts) parts.push(itemTypeCount(type, n));
	return parts.join(' · ');
}

export function movieCount(n: number): string {
	return `${n} movie${n === 1 ? '' : 's'}`;
}

// Plex stores language display names ("English"), Jellyfin ISO codes ("eng");
// Intl.DisplayNames (no runtime fetch) normalises codes, else fall back to raw.
let languageNames: Intl.DisplayNames | null | undefined;

function languageName(raw: string | null | undefined): string {
	const s = (raw || '').trim();
	if (!s) return '';
	if (!/^[a-z]{2,3}$/i.test(s)) return s;
	if (languageNames === undefined) {
		try {
			languageNames = new Intl.DisplayNames(['en'], { type: 'language' });
		} catch {
			languageNames = null;
		}
	}
	try {
		const name = languageNames?.of(s.toLowerCase());
		if (name && name.toLowerCase() !== s.toLowerCase()) return name;
	} catch {
		/* not a known code */
	}
	return s.toUpperCase();
}

const CODEC_LABELS: Record<string, string> = {
	aac: 'AAC',
	ac3: 'AC-3',
	eac3: 'E-AC-3',
	truehd: 'TrueHD',
	dts: 'DTS',
	'dts-hd ma': 'DTS-HD MA',
	dca: 'DTS',
	flac: 'FLAC',
	opus: 'Opus',
	mp3: 'MP3',
	mp2: 'MP2',
	pcm: 'PCM',
	vorbis: 'Vorbis'
};

export function codecLabel(raw: string | null | undefined): string {
	const s = (raw || '').trim();
	if (!s) return '';
	return CODEC_LABELS[s.toLowerCase()] ?? s.toUpperCase();
}

function channelLabel(n: number | null | undefined): string {
	if (!n) return '';
	switch (n) {
		case 1:
			return 'Mono';
		case 2:
			return 'Stereo';
		case 6:
			return '5.1';
		case 7:
			return '6.1';
		case 8:
			return '7.1';
		default:
			return `${n}ch`;
	}
}

export function audioTrackLabel(track: AudioTrack, idx: number): string {
	const language = languageName(track.language);
	const bits = [language, codecLabel(track.codec), channelLabel(track.channels)];
	let label = bits.filter(Boolean).join(' · ');
	const title = (track.title || '').trim();
	if (title && title !== `Track ${idx + 1}` && title.toLowerCase() !== language.toLowerCase()) {
		label = label ? `${label} - ${title}` : title;
	}
	return label || `Track ${idx + 1}`;
}

export function subtitleTrackLabel(track: SubtitleTrack, idx: number): string {
	const name = languageName(track.language) || `Track ${idx + 1}`;
	const flags = [track.forced && 'forced', track.sdh && 'SDH'].filter(Boolean);
	return flags.length ? `${name} (${flags.join(', ')})` : name;
}

/** The chosen features as editor blocks, for a running order laid out by hand. */
export function featureBlocks(items: SelectedItem[]): ProgrammeItemIn[] {
	return items.map((item, index) => {
		const base = { id: -(index + 1), order: index }; // negative: not yet saved
		if (item.kind === 'movie') {
			return {
				...base,
				type: 'movie',
				title: item.title,
				runtime: item.runtime ?? 0,
				details: {
					movie_id: item.id,
					audio_track: item.audio_track_index,
					subtitle_track: item.subtitle_track_index
				}
			};
		}
		return {
			...base,
			type: 'random_movie',
			title: item.label || 'Random movie',
			runtime: 0,
			details: {
				genre_ids: item.genre_ids,
				certification: item.certification,
				year_from: item.year_from,
				year_to: item.year_to,
				runtime_from: item.runtime_from,
				runtime_to: item.runtime_to
			}
		};
	});
}
