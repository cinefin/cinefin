import { formatRuntime } from '$lib/format';
import { itemTypeCount } from '$lib/item-types';
import type { components } from '$lib/api/types.gen';
import { slotFilterText, type SelectedItem } from './create-types';

export type TemplateDetail = components['schemas']['TemplateSchema'];
export type TemplateItem = components['schemas']['TemplateItemSchema'];

// `details` is a free-form dict in the OpenAPI schema; these are the keys the
// create page reads, mirrored from ProgrammeService._process_template_items.
export interface PreviewBlockDetails {
	certification?: string | null;
	count?: number;
	duration?: number | null;
	hold_black?: boolean;
	reference_movie_title?: string | null;
	matched_count?: number;
	for_random_movie?: boolean;
	ratings_system?: string | null;
	movie_title?: string | null;
	card_status?: string;
	estimated?: boolean;
	trailer_tag_name?: string | null;
}

export interface PreviewBlock {
	order: number;
	type: string;
	runtime: number;
	title: string;
	details: PreviewBlockDetails;
}

export interface ProgrammePreview {
	total_runtime: number;
	total_blocks: number;
	blocks: PreviewBlock[];
}

interface RowBase {
	key: string;
	order: number;
	number: number;
	runtime: number | null;
	estimated: boolean;
}

export interface SlotRow extends RowBase {
	kind: 'slot';
	featureNumber: number;
	slotIndex: number;
	item: SelectedItem | null;
}

export interface SupportRow extends RowBase {
	kind: 'support';
	type: string;
	title: string;
	note: string;
	cue: boolean;
	included: boolean;
}

export type RundownRow = SlotRow | SupportRow;

export function featureItems(detail: TemplateDetail | null): TemplateItem[] {
	if (!detail) return [];
	return detail.items
		.filter((item) => item.item_type === 'feature')
		.sort((a, b) => a.order - b.order);
}

export function slotFeatureNumbers(detail: TemplateDetail | null): number[] {
	return featureItems(detail).map((item, i) => item.feature_number ?? i + 1);
}

const ESTIMATED_TYPES = new Set(['trailer_rule', 'random_movie', 'audio_bumper']);

function seconds(value: number | null | undefined): string {
	if (!value) return '';
	return value >= 60 ? `${Math.round(value / 60)} min` : `${Math.round(value)} s`;
}

function supportText(
	item: TemplateItem,
	block: PreviewBlock | undefined
): { title: string; note: string } {
	const feature = item.bound_to_feature ?? item.certification_feature ?? 1;

	switch (item.item_type) {
		case 'trailer_rule': {
			const count = item.trailer_count ?? block?.details.count ?? 3;
			const notes = [itemTypeCount('trailer', count), `for feature ${feature}`];
			const criteria: string[] = [];
			if (item.match_genre) criteria.push('genre');
			if (item.match_certification) criteria.push('rating');
			if (item.match_year) criteria.push('year');
			if (criteria.length) notes.push(`matches ${criteria.join(', ')}`);
			const tag = item.trailer_tag?.name ?? block?.details.trailer_tag_name;
			if (tag) notes.push(`tagged ${tag}`);
			const matched = block?.details.matched_count;
			if (typeof matched === 'number') {
				notes.push(matched >= count ? `${matched} match` : `only ${matched} match`);
			}
			return {
				title: block?.details.reference_movie_title
					? `Trailers for ${block.details.reference_movie_title}`
					: 'Trailers',
				note: notes.join(' · ')
			};
		}
		case 'certification': {
			const cert = block?.details.certification;
			const system = block?.details.ratings_system;
			const notes = [`for feature ${item.certification_feature ?? feature}`];
			if (cert) notes.push(system ? `${system} ${cert}` : cert);
			return { title: 'Certification card', note: notes.join(' · ') };
		}
		case 'command': {
			const held = item.hold_black;
			const dwell = seconds(block?.details.duration);
			return {
				title: item.command?.name ?? block?.title ?? 'Command',
				note: held
					? dwell
						? `Holds black for at least ${dwell}`
						: 'Holds black until it finishes'
					: 'Fires as a cue - plays nothing'
			};
		}
		case 'bumper': {
			const tag = item.tag?.name;
			if (tag || item.tag) {
				return {
					title: block?.title ?? 'Random user media',
					note: [itemTypeCount('bumper', item.count || 1), tag ? `tagged ${tag}` : '']
						.filter(Boolean)
						.join(' · ')
				};
			}
			return { title: item.bumper?.title ?? block?.title ?? 'User media', note: '' };
		}
		case 'trailer':
			return { title: item.trailer?.title ?? block?.title ?? 'Trailer', note: '' };
		case 'audio_bumper':
			return {
				title: 'Audio intro',
				note: `matched to feature ${item.bound_to_feature ?? '?'}`
			};
		default:
			return { title: block?.title ?? '', note: '' };
	}
}

export function buildRundown(
	detail: TemplateDetail | null,
	slots: (SelectedItem | null)[],
	preview: ProgrammePreview | null
): RundownRow[] {
	if (!detail) return [];
	const blocks = new Map<number, PreviewBlock>();
	for (const block of preview?.blocks ?? []) blocks.set(block.order, block);

	const numbers = slotFeatureNumbers(detail);
	const items = [...detail.items].sort((a, b) => a.order - b.order);
	const rows: RundownRow[] = [];
	let slotIndex = 0;
	let number = 0;

	for (const item of items) {
		const block = blocks.get(item.order);
		if (item.item_type === 'feature') {
			const index = slotIndex++;
			const slotted = slots[index] ?? null;
			rows.push({
				kind: 'slot',
				key: `slot-${item.id}`,
				order: item.order,
				number: ++number,
				featureNumber: numbers[index] ?? index + 1,
				slotIndex: index,
				item: slotted,
				runtime: block?.runtime ?? (slotted?.kind === 'movie' ? slotted.runtime : null),
				estimated: slotted?.kind === 'random' || !!block?.details.estimated
			});
			continue;
		}
		const included = !preview || !!block;
		const { title, note } = supportText(item, block);
		rows.push({
			kind: 'support',
			key: `item-${item.id}`,
			order: item.order,
			number: included ? ++number : 0,
			type: item.item_type,
			title,
			note,
			cue: item.item_type === 'command' && !item.hold_black,
			included,
			runtime: block?.runtime ?? null,
			estimated: ESTIMATED_TYPES.has(item.item_type) || !!block?.details.estimated
		});
	}
	return rows;
}

// Shared column geometry: number · icon · title/facts · type badge · runtime.
export const rowCols = {
	number: 'w-6 shrink-0 text-right font-mono text-xs text-faint',
	icon: 'shrink-0 self-center',
	runtime: 'w-24 shrink-0 text-right font-mono text-xs whitespace-nowrap text-muted'
} as const;

// Seconds for sub-minute rows so idents/cards don't round to "0 min"; "≈" marks projections.
export function rowRuntime(minutes: number, estimated = false): string {
	const prefix = estimated ? '≈ ' : '';
	if (minutes < 1) return `${prefix}${Math.max(1, Math.round(minutes * 60))} s`;
	return `${prefix}${formatRuntime(minutes)}`;
}

export function slotMeta(item: SelectedItem): string {
	if (item.kind === 'random') return slotFilterText(item);
	const parts: string[] = [];
	if (item.year) parts.push(String(item.year));
	if (item.certification) parts.push(item.certification);
	return parts.join(' · ');
}

export function previewWarnings(preview: ProgrammePreview | null): string[] {
	const warnings: string[] = [];
	for (const block of preview?.blocks ?? []) {
		const d = block.details;
		if (block.type === 'trailer_rule') {
			const matched = d.matched_count;
			const title = d.reference_movie_title;
			if (title && matched !== undefined && matched < (d.count ?? 0)) {
				warnings.push(
					matched === 0
						? `No trailers match “${title}” - unrelated trailers will fill in`
						: `Only ${matched} of ${d.count} trailers match “${title}” - unrelated trailers will fill the rest`
				);
			}
		} else if (block.type === 'certification' && !d.for_random_movie) {
			switch (d.card_status) {
				case 'no_certificate':
					warnings.push(
						`“${d.movie_title}” has no ${d.ratings_system} certificate - the card will be skipped`
					);
					break;
				case 'invalid_certificate':
					warnings.push(
						`“${d.certification}” isn't a valid ${d.ratings_system} certificate - the card will be skipped`
					);
					break;
				case 'no_card_source':
					warnings.push(
						`No card background or static video for “${d.certification}” - add ratings/${d.ratings_system}/${d.certification}.mp4 (or a ratings/${d.certification}.jpg background) to your media folder`
					);
					break;
			}
		}
	}
	return warnings;
}
