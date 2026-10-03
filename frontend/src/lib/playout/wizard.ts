/**
 * The Add a player wizard's step logic, kept out of the component so it reads
 * in one place: the steps and when each can be entered, what a pairing error
 * means to the user, and which side of the test sound is playing.
 */
import { ApiError } from '$lib/api/client';

export type StepId = 'find' | 'pair' | 'screen' | 'finish';

export const STEPS: { id: StepId; label: string }[] = [
	{ id: 'find', label: 'Find' },
	{ id: 'pair', label: 'Pair' },
	{ id: 'screen', label: 'Screen and sound' },
	{ id: 'finish', label: 'Finish' }
];

/**
 * Which steps can be entered. Before pairing: finding, and pairing once a
 * player and a name are chosen. After: only the steps that act on the paired
 * player (going back to pair it again would make no sense).
 */
export function stepEnabled(id: StepId, s: { chosen: boolean; paired: boolean }): boolean {
	if (s.paired) return id === 'screen' || id === 'finish';
	if (id === 'find') return true;
	if (id === 'pair') return s.chosen;
	return false;
}

export const CODE_LENGTH = 6;

/** The digits of a typed or pasted code, at most six ("482 913" -> "482913"). */
export function codeDigits(text: string): string {
	return text.replace(/\D/g, '').slice(0, CODE_LENGTH);
}

/** A name to offer for a player typed in by address: its host name. */
export function nameFromAddress(address: string): string {
	const raw = address.trim();
	if (!raw) return '';
	try {
		return new URL(/^https?:\/\//.test(raw) ? raw : `http://${raw}`).hostname;
	} catch {
		return '';
	}
}

/**
 * What a failed pair call means, in words the user can act on. The player
 * cannot tell a wrong code from one that has run out (both are a 403), so one
 * message covers both.
 */
export function pairError(e: unknown): string {
	if (!(e instanceof ApiError)) return e instanceof Error ? e.message : 'Pairing failed.';
	switch (e.errorCode) {
		case 'PAIR_WRONG_CODE':
			return 'That code did not match, or it has run out. The code changes every 5 minutes and after each wrong try: enter the one on the screen now.';
		case 'AGENT_OUTDATED':
			return 'This player is too old for this Cinefin. Update cinefin-playout on it to the latest release, then pair again.';
		case 'AGENT_UNREACHABLE':
			return 'No player answered at that address. Check that cinefin-playout is running and the address is right.';
		default:
			return e.message;
	}
}

export interface SoundStep {
	channel: 'left' | 'right';
	start_ms: number;
	duration_ms: number;
}

/** The side sounding `elapsed` ms into the test sound, or null between and after. */
export function soundingAt(sequence: SoundStep[], elapsed: number): 'left' | 'right' | null {
	const step = sequence.find((s) => elapsed >= s.start_ms && elapsed < s.start_ms + s.duration_ms);
	return step?.channel ?? null;
}
