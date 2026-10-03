// Settings save themselves: a change schedules a save a moment later, so typing a name is one
// save, not one per key. One save runs at a time; a change made while it runs saves after it.
import { errorText } from './form.svelte';

export type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';

export class AutoSave {
	status = $state<SaveStatus>('idle');
	error = $state<string | null>(null);
	savedAt = $state<Date | null>(null);

	#run: () => Promise<void>;
	#ms: number;
	#timer: ReturnType<typeof setTimeout> | undefined;
	#running = false;
	#again = false;

	constructor(run: () => Promise<void>, ms = 700) {
		this.#run = run;
		this.#ms = ms;
	}

	schedule(): void {
		clearTimeout(this.#timer);
		this.#timer = setTimeout(() => void this.flush(), this.#ms);
	}

	/** Save now if a save is waiting (leaving the page, closing a panel). */
	async flush(): Promise<void> {
		clearTimeout(this.#timer);
		this.#timer = undefined;
		if (this.#running) {
			this.#again = true;
			return;
		}
		this.#running = true;
		this.status = 'saving';
		try {
			await this.#run();
			this.status = 'saved';
			this.error = null;
			this.savedAt = new Date();
		} catch (e) {
			this.status = 'error';
			this.error = errorText(e, 'Could not save');
		} finally {
			this.#running = false;
			if (this.#again) {
				this.#again = false;
				void this.flush();
			}
		}
	}

	/** A waiting save that has not started is dropped (the draft was reset). */
	cancel(): void {
		clearTimeout(this.#timer);
		this.#timer = undefined;
	}

	get waiting(): boolean {
		return this.#timer !== undefined;
	}
}
