/**
 * The playout status, read the same way on every surface: the lamp, the playout bar's lines
 * and which buttons are live. The server decides phase, label and actions; this only draws.
 */
import type { components } from '../api/types.gen';
import { dayLabel, formatClock, formatTime } from '../format.ts';

export type PlayoutStatus = components['schemas']['PlayoutStatusDataSchema'];
export type Phase = PlayoutStatus['phase'];
export type PlayoutAction = NonNullable<PlayoutStatus['actions']>[number];
export type NextScreening = NonNullable<PlayoutStatus['next_screening']>;

export interface Lamp {
	label: string;
	colour: 'green' | 'amber' | 'neutral' | 'red';
	/** On air: the solid red tally, not a lamp. */
	tally?: boolean;
	/** Muted words, for the settled idle state. */
	quiet?: boolean;
	/** Still finding out: the lamp breathes. */
	pending?: boolean;
}

const LAMPS: Record<Phase, Lamp> = {
	offline: { label: 'Offline', colour: 'amber' },
	standby: { label: 'Standby', colour: 'neutral', quiet: true },
	cued: { label: 'Cued', colour: 'green' },
	preshow: { label: 'On air', colour: 'red', tally: true },
	playing: { label: 'On air', colour: 'red', tally: true },
	hold: { label: 'On air', colour: 'red', tally: true },
	paused: { label: 'Paused', colour: 'amber' },
	manual: { label: 'On air · manual', colour: 'red', tally: true }
};

/** Cinefin itself is out of reach: whatever the last status said is no longer known. */
export const UNREACHABLE: Lamp = { label: 'Cinefin unreachable', colour: 'amber', pending: true };

/** The lamp for a status; `loaded` false while the first status is on its way. */
export function lamp(status: PlayoutStatus | null | undefined, loaded = true): Lamp {
	if (status) return LAMPS[status.phase];
	return loaded
		? { label: 'Status unavailable', colour: 'amber', quiet: true }
		: { label: 'Connecting…', colour: 'neutral', pending: true, quiet: true };
}

/** Whether the server allows `action` now (a button's enabled state). */
export function can(status: PlayoutStatus | null | undefined, action: PlayoutAction): boolean {
	return !!status?.actions?.includes(action);
}

/** A programme has started and not ended: the pre-show, an item, a pause or a hold. */
export function started(status: PlayoutStatus | null | undefined): boolean {
	return !!status?.programme && ['preshow', 'playing', 'paused', 'hold'].includes(status.phase);
}

/** The big transport button: Start when cued, Resume when paused, else Pause. */
export function primaryAction(status: PlayoutStatus | null | undefined): {
	action: 'start' | 'pause' | 'resume';
	label: string;
	enabled: boolean;
} {
	if (can(status, 'start')) return { action: 'start', label: 'Start', enabled: true };
	if (can(status, 'resume')) return { action: 'resume', label: 'Resume', enabled: true };
	return { action: 'pause', label: 'Pause', enabled: can(status, 'pause') };
}

/** The screening whose lead-in cued the loaded programme: its lead-in has begun. */
export function cuedBy(
	status: PlayoutStatus | null | undefined,
	now = Date.now()
): NextScreening | null {
	const s = status?.next_screening;
	return s && s.programme_id === status?.programme?.id && new Date(s.cue_time).getTime() <= now
		? s
		: null;
}

/** "Alien (1979) · Today 20:00, cues at 19:55". */
export function screeningLine(screening: NextScreening): string {
	const plays = new Date(screening.start_time);
	const cues = new Date(screening.cue_time);
	const at = `${dayLabel(plays)} ${formatClock(plays)}`;
	return cues.getTime() < plays.getTime()
		? `${screening.programme_name} · ${at}, cues at ${formatClock(cues)}`
		: `${screening.programme_name} · ${at}`;
}

export interface BarLines {
	/** The player's name, or the loaded programme's. */
	title: string;
	/** The item type to colour the start of the detail line with, if any. */
	type: string | null;
	detail: string;
}

/** The playout bar's two lines: what is loaded, and what is on screen. `address` is the player's,
 * from the host list: the status never carries it, since kiosks read it without a session. */
export function barLines(status: PlayoutStatus, address = ''): BarLines {
	const player = status.player?.name ?? 'Player';
	const item = status.current_item;
	const left = status.playback ? formatTime(status.playback.remaining) : '';
	const total = status.playlist?.total_items ?? 0;
	switch (status.phase) {
		case 'offline':
			return {
				title: player,
				type: null,
				detail: !status.player
					? 'No player is set up'
					: address
						? `Can't reach the player at ${address}`
						: "Can't reach the player"
			};
		case 'standby':
			return { title: player, type: null, detail: `On screen · ${status.screen}, held` };
		case 'manual':
		case 'paused':
			if (status.manual) return { title: 'Manual', type: null, detail: status.label };
			break;
	}
	const title = status.programme?.name ?? player;
	switch (status.phase) {
		case 'cued': {
			const onTitle = status.screen === 'Title card';
			const screening = cuedBy(status);
			const tail = screening
				? `starts ${formatClock(new Date(screening.start_time))}`
				: status.next_item
					? `First up: ${status.next_item.title}`
					: '';
			const screen = `On screen · ${status.screen}${onTitle ? ', held' : ''}`;
			return { title, type: null, detail: tail ? `${screen} · ${tail}` : screen };
		}
		case 'preshow':
			return { title, type: null, detail: `Pre-show · Title card · ${left} left` };
		case 'hold':
			return { title, type: 'command', detail: `${item?.title ?? ''} · ${left} left` }; // 'Hold ·'
		case 'paused':
			return { title, type: null, detail: status.label };
		default: {
			const at = item && item.position >= 0 ? `${item.position + 1} of ${total} · ` : '';
			return { title, type: item?.type ?? null, detail: `${at}${item?.title ?? ''}` };
		}
	}
}
