// Undo and redo for an auto-saving editor: snapshots of the whole document. A burst of edits to one
// field (typing in a text box) merges into one step, so undo takes back the word, not each letter.
// Plain (no runes) so node --test can run it; the editor mirrors canUndo/canRedo into its own state.
const MERGE_MS = 1000;
const LIMIT = 50;

export class History<T> {
	#undo: T[] = [];
	#redo: T[] = [];
	#base: T | null = null;
	#lastKey = '';
	#lastAt = 0;

	get canUndo() {
		return this.#undo.length > 0;
	}
	get canRedo() {
		return this.#redo.length > 0;
	}

	/** Start over from `current` (e.g. another document was opened). */
	reset(current: T) {
		this.#undo = [];
		this.#redo = [];
		this.#base = structuredClone(current);
		this.#lastKey = '';
	}

	/** `current` is the document after an edit; `key` names what changed, for merging. */
	record(current: T, key = '', now = Date.now()) {
		const merge = key !== '' && key === this.#lastKey && now - this.#lastAt < MERGE_MS;
		if (!merge && this.#base !== null) {
			this.#undo = [...this.#undo.slice(1 - LIMIT), this.#base];
			this.#redo = [];
		}
		this.#base = structuredClone(current);
		this.#lastKey = key;
		this.#lastAt = now;
	}

	/** The document before the last step, or null when there is nothing to undo. */
	undo(current: T): T | null {
		const target = this.#undo.pop();
		if (target === undefined) return null;
		this.#redo.push(structuredClone(current));
		return this.#moveTo(target);
	}

	redo(current: T): T | null {
		const target = this.#redo.pop();
		if (target === undefined) return null;
		this.#undo.push(structuredClone(current));
		return this.#moveTo(target);
	}

	#moveTo(target: T): T {
		this.#base = structuredClone(target);
		this.#lastKey = '';
		return structuredClone(target);
	}
}
