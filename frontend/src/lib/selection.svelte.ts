import { SvelteSet } from 'svelte/reactivity';

/**
 * A list page's multi-select: a reactive set of ids over the items currently shown, with
 * shift-click range toggling and select-all over what is visible.
 */
export class Selection extends SvelteSet<number> {
	#items: () => { id: number }[];
	#anchor: number | null = null; // shift-click range anchor

	constructor(items: () => { id: number }[]) {
		super();
		this.#items = items;
	}

	/** Every visible item is selected (and there is at least one). */
	get allVisible(): boolean {
		const items = this.#items();
		return items.length > 0 && items.every((i) => this.has(i.id));
	}

	set(id: number, on: boolean) {
		if (on) this.add(id);
		else this.delete(id);
	}

	/** Toggle one item; with `shift`, extend the last toggle across the visible range. */
	toggle(id: number, on: boolean, shift = false) {
		const items = this.#items();
		const a = items.findIndex((i) => i.id === this.#anchor);
		const b = items.findIndex((i) => i.id === id);
		if (shift && this.#anchor !== id && a !== -1 && b !== -1) {
			for (let i = Math.min(a, b); i <= Math.max(a, b); i++) this.set(items[i].id, on);
		} else {
			this.set(id, on);
		}
		this.#anchor = id;
	}

	/** Select or deselect every visible item (others keep their state). */
	setVisible(on: boolean) {
		for (const i of this.#items()) this.set(i.id, on);
		this.#anchor = null;
	}

	override clear() {
		super.clear();
		this.#anchor = null;
	}
}
