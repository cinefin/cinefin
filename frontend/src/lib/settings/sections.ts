// The Settings page's sections, in the toolbar's order, chosen by ?tab=.
import {
	Database,
	Film,
	Lock,
	MonitorPlay,
	Palette,
	Puzzle,
	Server,
	Ticket,
	Tv,
	type LucideIcon
} from '@lucide/svelte';

export interface SettingsSectionInfo {
	id: string;
	/** The toolbar's short name. */
	label: string;
	icon: LucideIcon;
	blurb: string;
}

export const SETTINGS_SECTIONS = [
	{
		id: 'playout',
		label: 'Playout',
		icon: MonitorPlay,
		blurb: 'The machine at the screen, its picture and sound, and what plays around a programme.'
	},
	{
		id: 'library',
		label: 'Library',
		icon: Server,
		blurb: 'The one media server your films come from, and the TMDB key that enriches them.'
	},
	{
		id: 'cinema',
		label: 'Theater',
		icon: Film,
		blurb: "Your theater's identity and seating, and the certification cards shown before features."
	},
	{
		id: 'tickets',
		label: 'Tickets',
		icon: Ticket,
		blurb: 'Ticket designs and the thermal printer they print on.'
	},
	{
		id: 'plugins',
		label: 'Plugins',
		icon: Puzzle,
		blurb: 'The kinds of action your commands can run, and the connection settings they need.'
	},
	{
		id: 'kiosk',
		label: 'Kiosk',
		icon: Tv,
		blurb: 'Defaults for every kiosk screen; each display can still override them.'
	},
	{
		id: 'appearance',
		label: 'Appearance',
		icon: Palette,
		blurb: 'How the web app looks - the navbar logo, accent colour and clock format.'
	},
	{
		id: 'security',
		label: 'Security',
		icon: Lock,
		blurb: 'Require a login to reach Cinefin, and mint API keys for programmatic access.'
	},
	{
		id: 'backup',
		label: 'Backup',
		icon: Database,
		blurb: 'Save a complete copy of your Cinefin database, and restore it if something goes wrong.'
	}
] as const satisfies readonly SettingsSectionInfo[];

export type SettingsSection = (typeof SETTINGS_SECTIONS)[number]['id'];

/** The section a settings URL shows: its ?tab=, else the first. */
export function settingsSectionOf(url: URL): SettingsSection {
	const tab = url.searchParams.get('tab');
	return SETTINGS_SECTIONS.find((s) => s.id === tab)?.id ?? 'playout';
}
