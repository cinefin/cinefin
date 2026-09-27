/**
 * Which commands a surface (the dashboard, the remote) shows as buttons, in order.
 * Per device on purpose — the booth tablet and the laptop can differ — so it lives
 * in localStorage, which can throw or come back empty; a device with no picks
 * shows none until some are chosen there.
 */
export type Surface = 'dashboard' | 'remote';

const key = (surface: Surface) => `cpx-command-picks-${surface}`;

function read(surface: Surface): number[] {
	try {
		const ids = JSON.parse(localStorage.getItem(key(surface)) ?? '[]');
		return Array.isArray(ids) ? ids.filter((id) => Number.isInteger(id)) : [];
	} catch {
		return [];
	}
}

export class CommandPicks {
	ids = $state<number[]>([]);
	#surface: Surface;

	constructor(surface: Surface) {
		this.#surface = surface;
		this.ids = read(surface);
	}

	save(ids: number[]): void {
		this.ids = ids;
		try {
			localStorage.setItem(key(this.#surface), JSON.stringify(ids));
		} catch {
			/* storage blocked: the picks last for this visit only */
		}
	}
}
