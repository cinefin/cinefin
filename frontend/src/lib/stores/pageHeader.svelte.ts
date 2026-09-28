/** The current page's heading, rendered by the topbar (set via `PageHeader`). */
import type { Snippet } from 'svelte';

export interface PageHeaderSpec {
	title: string;
	count?: string;
	back?: { href: string; label: string };
	actions?: Snippet;
}

class PageHeaderStore {
	current = $state.raw<PageHeaderSpec | null>(null);
}

export const pageHeader = new PageHeaderStore();
