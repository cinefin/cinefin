/** Shared filter-toolbar contract (types FilterBar.svelte renders) + signed-sort helpers. */

export interface FilterOption {
	value: string;
	label: string;
	count?: number;
}

export interface SelectFilter {
	kind?: 'select';
	id: string;
	label: string;
	allLabel: string;
	value: string;
	options: FilterOption[];
	onchange: (value: string) => void;
	/** Render no control — appears only as a clearable chip when set (click-to-filter targets). */
	chipOnly?: boolean;
}

export interface ToggleFilter {
	kind: 'toggle';
	id: string;
	label: string;
	value: boolean;
	onchange: (value: boolean) => void;
}

/** A multi-value facet with AND semantics — an item must carry ALL picked values. */
export interface MultiSelectFilter {
	kind: 'multi';
	id: string;
	label: string;
	values: string[];
	options: FilterOption[];
	onchange: (values: string[]) => void;
}

export type FilterControl = SelectFilter | ToggleFilter | MultiSelectFilter;

/** The sort dropdown. `value` is a signed key ("-year" = year descending). */
export interface SortSpec {
	value: string;
	options: FilterOption[];
	default: string;
	onchange: (value: string) => void;
}

export function isToggle(f: FilterControl): f is ToggleFilter {
	return f.kind === 'toggle';
}

export function isMulti(f: FilterControl): f is MultiSelectFilter {
	return f.kind === 'multi';
}

export function anyFilterActive(filters: FilterControl[]): boolean {
	return filters.some((f) =>
		isToggle(f) ? f.value : isMulti(f) ? f.values.length > 0 : f.value !== ''
	);
}

/** Column-header click: toggle direction if already active, else start from natural direction. */
export function toggleSort(current: string, key: string, defaultDesc = false): string {
	if (current === key) return `-${key}`;
	if (current === `-${key}`) return key;
	return defaultDesc ? `-${key}` : key;
}

export function sortIndicator(current: string, key: string): string {
	if (current === key) return '▲';
	if (current === `-${key}`) return '▼';
	return '';
}

/**
 * Client-side row sort for fully-loaded tables. Null/undefined always sort last (regardless
 * of direction); numbers compare numerically, else numeric-aware locale compare. Stable.
 */
export function sortRows<T>(
	rows: T[],
	sort: string,
	accessors: Record<string, (row: T) => string | number | null | undefined>
): T[] {
	if (!sort) return rows;
	const desc = sort.startsWith('-');
	const key = desc ? sort.slice(1) : sort;
	const get = accessors[key];
	if (!get) return rows;
	const dir = desc ? -1 : 1;
	return [...rows].sort((a, b) => {
		const va = get(a);
		const vb = get(b);
		if (va == null && vb == null) return 0;
		if (va == null) return 1;
		if (vb == null) return -1;
		const cmp =
			typeof va === 'number' && typeof vb === 'number'
				? va - vb
				: String(va).localeCompare(String(vb), undefined, { numeric: true });
		return dir * cmp;
	});
}
