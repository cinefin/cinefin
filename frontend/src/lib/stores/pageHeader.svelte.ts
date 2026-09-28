/** The current page's heading, rendered by the topbar (set via `PageHeader`). */
import type { Snippet } from 'svelte';
import type { ItemTypeFamily } from '$lib/item-types';

export interface PageHeaderSpec {
	title: string;
	count?: string;
	back?: { href: string; label: string };
	actions?: Snippet;
	/** A content page's colour: the family its items carry in a rundown. */
	tone?: ItemTypeFamily;
}

class PageHeaderStore {
	current = $state.raw<PageHeaderSpec | null>(null);
}

export const pageHeader = new PageHeaderStore();
