/**
 * THE single source of truth for how a programme / playlist item type is named, iconed and
 * coloured. Six colour families (film gold, trailer violet, media cyan, command indigo,
 * certification rose, system slate) as `--color-type-*` tokens in app.css — use the token
 * utilities below, never hex. Application rule: coloured icon + tinted badge (via TypeBadge) +
 * a 2px left edge on a row/card that IS one item; rows/headers stay on the neutral surface.
 * Adding a type? Add it HERE — never map labels, icons or colours locally.
 */
import {
	BadgeCheck,
	Clapperboard,
	Dices,
	Film,
	ImagePlay,
	ListVideo,
	Shuffle,
	SquareTerminal,
	Type,
	Video,
	Volume2,
	Wand,
	type LucideIcon
} from '@lucide/svelte';
import type { Component } from 'svelte';

export const ITEM_TYPE_FAMILIES = [
	'film',
	'trailer',
	'media',
	'command',
	'certification',
	'system'
] as const;

export type ItemTypeFamily = (typeof ITEM_TYPE_FAMILIES)[number];

export interface ItemTypeClasses {
	icon: string;
	/** Badge tint + hairline border + label colour. */
	badge: string;
	/** The 2px left edge for a row/card that represents one item. */
	edge: string;
	/** Solid fill, for timeline segments and meters. */
	bar: string;
}

// Written out per family (no string interpolation) so Tailwind's source scan sees every class.
const FAMILY_CLASSES: Record<ItemTypeFamily, ItemTypeClasses> = {
	film: {
		icon: 'text-type-film',
		badge: 'border border-type-film/30 bg-type-film/15 text-type-film',
		edge: 'border-l-2 border-l-type-film',
		bar: 'bg-type-film'
	},
	trailer: {
		icon: 'text-type-trailer',
		badge: 'border border-type-trailer/30 bg-type-trailer/15 text-type-trailer',
		edge: 'border-l-2 border-l-type-trailer',
		bar: 'bg-type-trailer'
	},
	media: {
		icon: 'text-type-media',
		badge: 'border border-type-media/30 bg-type-media/15 text-type-media',
		edge: 'border-l-2 border-l-type-media',
		bar: 'bg-type-media'
	},
	command: {
		icon: 'text-type-command',
		badge: 'border border-type-command/30 bg-type-command/15 text-type-command',
		edge: 'border-l-2 border-l-type-command',
		bar: 'bg-type-command'
	},
	certification: {
		icon: 'text-type-certification',
		badge: 'border border-type-certification/30 bg-type-certification/15 text-type-certification',
		edge: 'border-l-2 border-l-type-certification',
		bar: 'bg-type-certification'
	},
	system: {
		icon: 'text-type-system',
		badge: 'border border-type-system/30 bg-type-system/15 text-type-system',
		edge: 'border-l-2 border-l-type-system',
		bar: 'bg-type-system'
	}
};

export interface ItemTypeMeta {
	type: string;
	label: string;
	/** Compact operator wording for tight rows. */
	short: string;
	/** Lowercase GLOSSARY noun, [singular, plural]. */
	noun: readonly [string, string];
	family: ItemTypeFamily;
	icon: LucideIcon;
}

const ITEM_TYPES: Record<string, ItemTypeMeta> = {
	movie: {
		type: 'movie',
		label: 'Movie',
		short: 'Feature',
		noun: ['movie', 'movies'],
		family: 'film',
		icon: Film
	},
	feature: {
		type: 'feature',
		label: 'Feature',
		short: 'Feature',
		noun: ['feature', 'features'],
		family: 'film',
		icon: Film
	},
	random_movie: {
		type: 'random_movie',
		// "Random", not "Movie": it sits beside real movie blocks and must read as distinct.
		label: 'Random movie',
		short: 'Random',
		noun: ['random movie', 'random movies'],
		family: 'film',
		icon: Dices
	},
	trailer: {
		type: 'trailer',
		label: 'Trailer',
		short: 'Trailer',
		noun: ['trailer', 'trailers'],
		family: 'trailer',
		icon: Clapperboard
	},
	trailer_rule: {
		type: 'trailer_rule',
		label: 'Trailer rule',
		short: 'Trailers',
		noun: ['trailer rule', 'trailer rules'],
		family: 'trailer',
		icon: Wand
	},
	bumper: {
		type: 'bumper',
		label: 'User media',
		short: 'Media',
		noun: ['user media item', 'user media items'],
		family: 'media',
		icon: ImagePlay
	},
	random_bumper: {
		type: 'random_bumper',
		label: 'Random user media',
		short: 'Media',
		noun: ['random user media', 'random user media'],
		family: 'media',
		icon: Shuffle
	},
	audio_bumper: {
		type: 'audio_bumper',
		label: 'Audio user media',
		short: 'Audio',
		noun: ['audio intro', 'audio intros'],
		family: 'media',
		icon: Volume2
	},
	command: {
		type: 'command',
		// A command that appears in a rundown is always a hold (instant cues emit no item).
		label: 'Command',
		short: 'Hold',
		noun: ['command', 'commands'],
		family: 'command',
		icon: SquareTerminal
	},
	certification: {
		type: 'certification',
		label: 'Certification',
		short: 'Cert',
		noun: ['certification card', 'certification cards'],
		family: 'certification',
		icon: BadgeCheck
	},
	system: {
		type: 'system',
		label: 'System',
		short: 'System',
		noun: ['system item', 'system items'],
		family: 'system',
		icon: ListVideo
	},
	ident: {
		type: 'ident',
		label: 'System Ident',
		short: 'Ident',
		noun: ['system ident', 'system idents'],
		family: 'system',
		icon: Video
	},
	title: {
		type: 'title',
		label: 'Title card',
		short: 'Title',
		noun: ['title card', 'title cards'],
		family: 'system',
		icon: Type
	}
};

/** Label an instant command block — it fires as a cue, playing nothing. */
export const CUE_LABEL = 'Cue';

/** "trailer_rule" → "Trailer rule" for an unregistered type. */
function prettify(type: string): string {
	const words = type.replace(/[_-]+/g, ' ').trim();
	return words ? words.charAt(0).toUpperCase() + words.slice(1) : 'Item';
}

/** Metadata for a type — unknown/blank types fall back to the system family. */
export function itemType(type: string | null | undefined): ItemTypeMeta {
	const key = (type ?? '').trim();
	const known = ITEM_TYPES[key];
	if (known) return known;
	const label = prettify(key);
	return {
		type: key || 'unknown',
		label,
		short: label,
		noun: [label.toLowerCase(), label.toLowerCase()],
		family: 'system',
		icon: ListVideo
	};
}

/** Display name; `short` gives the compact operator wording. */
export function itemTypeLabel(type: string | null | undefined, opts?: { short?: boolean }): string {
	const meta = itemType(type);
	return opts?.short ? meta.short : meta.label;
}

export function itemTypeIcon(type: string | null | undefined): LucideIcon {
	return itemType(type).icon;
}

export function itemTypeFamily(type: string | null | undefined): ItemTypeFamily {
	return itemType(type).family;
}

export function itemTypeClasses(type: string | null | undefined): ItemTypeClasses {
	return FAMILY_CLASSES[itemType(type).family];
}

export interface ItemTypeDisplay extends ItemTypeMeta {
	classes: ItemTypeClasses;
}

/** Everything a consumer needs in one call. Pages should not re-derive any of it. */
export function itemTypeDisplay(type: string | null | undefined): ItemTypeDisplay {
	const meta = itemType(type);
	return { ...meta, classes: FAMILY_CLASSES[meta.family] };
}

/** "1 trailer rule" / "3 trailer rules" — the breakdown-line phrasing. */
export function itemTypeCount(type: string | null | undefined, n: number): string {
	const [one, many] = itemType(type).noun;
	return n === 1 ? one : `${n} ${many}`;
}
