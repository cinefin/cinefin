// The app's sections, shared by the sidebar (the links) and the topbar (the
// current group's colour). Grouped by what you are doing, not by where the code lives.
import { base } from '$app/paths';
import {
	CalendarClock,
	Clapperboard,
	Film,
	FolderOpen,
	LayoutDashboard,
	Layers,
	ListVideo,
	MonitorPlay,
	PaintbrushVertical,
	Settings,
	SquareTerminal,
	type LucideIcon
} from '@lucide/svelte';
import type { ItemTypeFamily } from '$lib/item-types';

export interface NavItem {
	href: string;
	label: string;
	icon: LucideIcon;
}

export interface NavGroup {
	/** Sentence-case group label; shown only in the expanded sidebar. */
	label: string;
	/** The group's colour: a square before each page's title, a wash in the topbar. */
	tone: ItemTypeFamily;
	items: NavItem[];
}

export const NAV_GROUPS: NavGroup[] = [
	{
		label: 'Operate',
		tone: 'media',
		items: [
			{ href: '/', label: 'Dashboard', icon: LayoutDashboard },
			{ href: '/remote', label: 'Remote', icon: MonitorPlay }
		]
	},
	{
		label: 'Content',
		tone: 'film',
		items: [
			{ href: '/library', label: 'Library', icon: Film },
			{ href: '/trailers', label: 'Trailers', icon: Clapperboard },
			{ href: '/media', label: 'Media', icon: FolderOpen },
			{ href: '/schedules', label: 'Schedules', icon: CalendarClock }
		]
	},
	{
		label: 'Programme',
		tone: 'trailer',
		items: [
			{ href: '/programmes', label: 'Programmes', icon: ListVideo },
			{ href: '/templates', label: 'Templates', icon: Layers },
			{ href: '/titles', label: 'Titles', icon: PaintbrushVertical }
		]
	},
	{
		label: 'System',
		tone: 'system',
		items: [
			{ href: '/commands', label: 'Commands', icon: SquareTerminal },
			{ href: '/settings', label: 'Settings', icon: Settings }
		]
	}
];

const allHrefs = NAV_GROUPS.flatMap((g) => g.items.map((i) => i.href));

function matches(href: string, path: string): boolean {
	const target = `${base}${href}`.replace(/\/$/, '') || '/';
	if (href === '/') return path === target;
	return path === target || path.startsWith(`${target}/`);
}

/**
 * The most specific nav entry wins: /programmes/create is a child of
 * /programmes, and only the deeper one should light up.
 */
export function isActive(href: string, pathname: string): boolean {
	const path = pathname.replace(/\/$/, '') || '/';
	if (!matches(href, path)) return false;
	return !allHrefs.some(
		(other) => other !== href && other.startsWith(href) && matches(other, path)
	);
}

export function navGroupFor(pathname: string): NavGroup | null {
	return NAV_GROUPS.find((g) => g.items.some((i) => isActive(i.href, pathname))) ?? null;
}
