// The ticket designer's vocabulary: every element kind and every choice an element or design offers,
// in one place. The element types come from the API schema; the choices mirror it.
import {
	ArrowUpDown,
	BadgeCheck,
	Barcode,
	Columns2,
	Image,
	Minus,
	QrCode,
	Type
} from '@lucide/svelte';
import type { LucideIcon } from '@lucide/svelte';
import type { components } from '$lib/api/types.gen';

type Schemas = components['schemas'];
/** One element as the API types it (backend/cinefin/api/schemas/tickets.py). */
export type Element =
	| Schemas['TextElement']
	| Schemas['ImageElement']
	| Schemas['RatingElement']
	| Schemas['QrElement']
	| Schemas['BarcodeElement']
	| Schemas['RuleElement']
	| Schemas['SpacerElement']
	| Schemas['ColumnsElement'];

/** An element as the editor handles it: every kind's fields, read loosely, so one form can edit any of
 * them. Kept honest by the check below: every API element must fit it. */
export interface TicketElement {
	type: Element['type'];
	align?: 'left' | 'center' | 'right';
	size?: 'normal' | 'wide' | 'tall' | 'large';
	bold?: boolean;
	invert?: boolean;
	content?: string;
	/** qr: 'fun' (a surprise link) or 'content' */
	mode?: 'fun' | 'content';
	error?: 'low' | 'medium' | 'quartile' | 'high';
	render?: 'image' | 'printer';
	/** spacer */
	lines?: number;
	/** image */
	file?: string;
	/** image, rating, qr: the share (%) of the paper or cell to fill; an image's null is its own size */
	width?: number | null;
	symbology?: Schemas['BarcodeElement']['symbology'];
	/** columns: relative cell widths, and each cell's stack of elements */
	widths?: number[];
	cells?: TicketElement[][];
}
// Fails `npm run check` when the API's elements stop fitting the editor's type.
null as unknown as Element satisfies TicketElement;

/** Set one field of an element, as the forms do (they edit any kind through one key/value channel). */
export function setField(el: TicketElement, key: keyof TicketElement, value: unknown) {
	(el as unknown as Record<string, unknown>)[key] = value;
}

/** What a design is, as the designer edits it. */
export interface DesignDraft {
	name: string;
	elements: TicketElement[];
	date_format: string;
	time_format: string;
	qr_links: string[];
	font: string;
}

export interface Design extends DesignDraft {
	id: number;
	is_default: boolean;
}

/** Where the selection is: a line, or a cell of a columns line, or an item in that cell. */
export interface Selection {
	index: number;
	cell?: number;
	item?: number;
}

export type Preview = Schemas['TicketPreviewDataSchema'];

interface Kind {
	label: string;
	icon: LucideIcon;
	/** A new element of this kind. */
	make: () => TicketElement;
	/** Can it sit in a columns cell? */
	inCell: boolean;
}

export const KINDS: Record<string, Kind> = {
	text: {
		label: 'Text',
		icon: Type,
		inCell: true,
		make: () => ({ type: 'text', content: 'Text' })
	},
	image: { label: 'Image', icon: Image, inCell: true, make: () => ({ type: 'image' }) },
	rating: {
		label: 'Rating symbol',
		icon: BadgeCheck,
		inCell: true,
		make: () => ({ type: 'rating', width: 25 })
	},
	qr: {
		label: 'QR code',
		icon: QrCode,
		inCell: true,
		make: () => ({ type: 'qr', mode: 'fun', width: 50 })
	},
	barcode: {
		label: 'Barcode',
		icon: Barcode,
		inCell: false,
		make: () => ({ type: 'barcode', content: '{ticket_no}' })
	},
	columns: {
		label: 'Columns',
		icon: Columns2,
		inCell: false,
		make: () => ({
			type: 'columns',
			widths: [1, 2],
			cells: [
				[{ type: 'qr', mode: 'fun', width: 100 }],
				[
					{ type: 'text', content: '{film_list}', align: 'left', bold: true },
					{ type: 'text', content: 'Seat {seat}', align: 'left' }
				]
			]
		})
	},
	rule: { label: 'Divider', icon: Minus, inCell: true, make: () => ({ type: 'rule' }) },
	spacer: {
		label: 'Spacer',
		icon: ArrowUpDown,
		inCell: true,
		make: () => ({ type: 'spacer', lines: 1 })
	}
};

export const kindOf = (el: TicketElement) => KINDS[el.type] ?? KINDS.text;

export interface Choice<T = string> {
	id: T;
	label: string;
	hint?: string;
}

export const TOKENS: Choice[] = [
	{
		id: 'film',
		label: 'Film',
		hint: "The feature's title - only when the programme has exactly one feature (use All films for the general case)"
	},
	{
		id: 'film_list',
		label: 'All films',
		hint: 'One line per feature: title, year and certificate'
	},
	{ id: 'seat', label: 'Seat' },
	{ id: 'date', label: 'Date' },
	{ id: 'time', label: 'Time' },
	{
		id: 'showtime',
		label: 'Showtime',
		hint: 'Date and time of the scheduled screening - blank when printing without a showtime'
	},
	{ id: 'ticket_no', label: 'Ticket number', hint: 'The running ticket number' },
	{ id: 'cinema', label: 'Cinema name' },
	{ id: 'programme', label: 'Programme', hint: "The programme's name" }
];

export const ALIGNMENTS: Choice<NonNullable<TicketElement['align']>>[] = [
	{ id: 'left', label: 'Left' },
	{ id: 'center', label: 'Centre' },
	{ id: 'right', label: 'Right' }
];
export const TEXT_SIZES: Choice<NonNullable<TicketElement['size']>>[] = [
	{ id: 'normal', label: 'Normal' },
	{ id: 'wide', label: 'Wide' },
	{ id: 'tall', label: 'Tall' },
	{ id: 'large', label: 'Large' }
];
export const BARCODES: Choice<NonNullable<TicketElement['symbology']>>[] = [
	{ id: 'code128', label: 'Code 128' },
	{ id: 'code39', label: 'Code 39' },
	{ id: 'ean13', label: 'EAN-13' },
	{ id: 'ean8', label: 'EAN-8' },
	{ id: 'upca', label: 'UPC-A' },
	{ id: 'itf', label: 'ITF (Interleaved 2 of 5)' },
	{ id: 'codabar', label: 'Codabar' }
];
export const QR_ERRORS: Choice<NonNullable<TicketElement['error']>>[] = [
	{ id: 'low', label: 'Low (7%)' },
	{ id: 'medium', label: 'Medium (15%)' },
	{ id: 'quartile', label: 'Quartile (25%)' },
	{ id: 'high', label: 'High (30%)' }
];
export const QR_RENDERS: Choice<NonNullable<TicketElement['render']>>[] = [
	{ id: 'image', label: 'Cinefin, as an image' },
	{ id: 'printer', label: "The printer's own QR" }
];
export const COLUMN_WIDTHS: Choice<number[]>[] = [
	{ id: [1, 1], label: 'Halves' },
	{ id: [1, 2], label: 'Narrow, wide' },
	{ id: [2, 1], label: 'Wide, narrow' },
	{ id: [1, 1, 1], label: 'Thirds' },
	{ id: [1, 2, 1], label: 'Wide middle' }
];
export const FONTS: Choice[] = [
	{ id: 'courier', label: 'Courier Prime', hint: 'Matches the printer' },
	{ id: 'inter', label: 'Inter' },
	{ id: 'oswald', label: 'Oswald' },
	{ id: 'bebas', label: 'Bebas Neue' },
	{ id: 'playfair', label: 'Playfair Display' }
];
export const DATE_FORMATS: Choice[] = [
	{ id: '%d/%m/%Y', label: '31/12/2026' },
	{ id: '%m/%d/%Y', label: '12/31/2026' },
	{ id: '%Y-%m-%d', label: '2026-12-31' },
	{ id: '%a %d %b %Y', label: 'Thu 31 Dec 2026' }
];
export const TIME_FORMATS: Choice[] = [
	{ id: '%H:%M', label: '19:30' },
	{ id: '%I:%M %p', label: '07:30 PM' }
];

/** What a new design can start from (backend ticket_service.STARTER_DESIGNS). */
export const STARTERS: Choice<'standard' | 'compact' | 'blank'>[] = [
	{ id: 'standard', label: 'Standard', hint: 'The full layout: cinema, seat, films, rating, QR' },
	{ id: 'compact', label: 'Compact', hint: 'A QR code beside the details, in columns' },
	{ id: 'blank', label: 'Blank' }
];
