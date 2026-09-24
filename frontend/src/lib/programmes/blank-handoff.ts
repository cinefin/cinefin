import type { ProgrammeItemIn } from '$lib/editor/programme-adapter';
import type { SelectedItem } from '$lib/programmes/create-types';

const KEY = 'cpx-blank-programme-films';

export function stashFilmsForBlankEditor(items: SelectedItem[]): void {
	const blocks: ProgrammeItemIn[] = items.map((item, index) => {
		if (item.kind === 'movie') {
			return {
				id: -(index + 1), // negative: not yet saved
				order: index,
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
			id: -(index + 1),
			order: index,
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

	try {
		sessionStorage.setItem(KEY, JSON.stringify(blocks));
	} catch {
		// noop
	}
}

export function takeStashedFilms(): ProgrammeItemIn[] {
	try {
		const raw = sessionStorage.getItem(KEY);
		if (!raw) return [];
		sessionStorage.removeItem(KEY);
		const parsed = JSON.parse(raw);
		return Array.isArray(parsed) ? (parsed as ProgrammeItemIn[]) : [];
	} catch {
		return [];
	}
}
