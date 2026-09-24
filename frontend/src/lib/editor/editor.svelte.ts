import type { BlockContent, BlockDetails, EditorBlock } from './types';
import { SvelteSet } from 'svelte/reactivity';

interface Snapshot<M> {
	blocks: EditorBlock[];
	meta: M;
	// Undoing a delete restores the block's open/collapsed state, not collapsed.
	expanded: string[];
}

const UNDO_LIMIT = 50;

export class BlockEditor<M = Record<string, unknown>> {
	blocks = $state<EditorBlock[]>([]);
	dirty = $state(false);
	showValidation = $state(false);
	selected = $state<number | null>(null);
	// uids of blocks whose config panels are open. Starts empty on load (the
	// list reads first); a block you add opens. Keyed by uid so it survives moves.
	expanded = $state<SvelteSet<string>>(new SvelteSet());
	canUndo = $state(false);
	canRedo = $state(false);

	#undo: Snapshot<M>[] = [];
	#redo: Snapshot<M>[] = [];
	#uid = 0;
	#captureMeta: () => M;
	#restoreMeta: (meta: M) => void;

	constructor(opts: { captureMeta: () => M; restoreMeta: (meta: M) => void }) {
		this.#captureMeta = opts.captureMeta;
		this.#restoreMeta = opts.restoreMeta;
	}

	uid(): string {
		return `blk_${this.#uid++}`;
	}

	markDirty(): void {
		this.dirty = true;
	}

	reset(blocks: EditorBlock[]): void {
		this.blocks = blocks;
		this.dirty = false;
		this.showValidation = false;
		this.selected = null;
		this.expanded = new SvelteSet();
		this.#undo = [];
		this.#redo = [];
		this.#syncFlags();
	}

	#capture(): Snapshot<M> {
		return {
			blocks: $state.snapshot(this.blocks) as EditorBlock[],
			meta: structuredClone(this.#captureMeta()),
			expanded: [...this.expanded]
		};
	}

	#restore(snapshot: Snapshot<M>): void {
		this.blocks = snapshot.blocks;
		this.#restoreMeta(snapshot.meta);
		this.expanded = new SvelteSet(snapshot.expanded);
		this.markDirty();
		if (this.selected !== null && this.selected >= this.blocks.length) this.selected = null;
	}

	#syncFlags(): void {
		this.canUndo = this.#undo.length > 0;
		this.canRedo = this.#redo.length > 0;
	}

	pushUndo(): void {
		this.#undo.push(this.#capture());
		if (this.#undo.length > UNDO_LIMIT) this.#undo.shift();
		this.#redo = [];
		this.#syncFlags();
	}

	discardLast(): void {
		this.#undo.pop();
		this.#syncFlags();
	}

	undo(): boolean {
		const snapshot = this.#undo.pop();
		if (!snapshot) return false;
		this.#redo.push(this.#capture());
		this.#restore(snapshot);
		this.#syncFlags();
		return true;
	}

	redo(): boolean {
		const snapshot = this.#redo.pop();
		if (!snapshot) return false;
		this.#undo.push(this.#capture());
		this.#restore(snapshot);
		this.#syncFlags();
		return true;
	}

	commit(mutate: () => void): void {
		this.pushUndo();
		mutate();
		this.markDirty();
	}

	#renumber(): void {
		this.blocks.forEach((b, i) => (b.order = i));
	}

	// Returns the block AS STORED (the $state proxy), not the object we built:
	// callers write the picked item back through this reference, and writes to
	// the raw object behind the proxy notify nothing.
	add(type: string, content: BlockContent, details: BlockDetails = {}): EditorBlock {
		this.pushUndo();
		this.blocks.push({
			uid: this.uid(),
			type,
			order: this.blocks.length,
			content,
			details
		});
		const stored = this.blocks[this.blocks.length - 1];
		this.markDirty();
		this.expanded.add(stored.uid);
		return stored;
	}

	move(index: number, direction: number): void {
		const target = index + direction;
		if (target < 0 || target >= this.blocks.length) return;
		this.pushUndo();
		const arr = this.blocks;
		[arr[index], arr[target]] = [arr[target], arr[index]];
		this.#renumber();
		this.markDirty();
		if (this.selected === index) this.selected = target;
	}

	reorder(from: number, to: number): void {
		if (from === to) return;
		this.pushUndo();
		const [moved] = this.blocks.splice(from, 1);
		this.blocks.splice(to, 0, moved);
		this.#renumber();
		this.markDirty();
		this.selected = null;
	}

	duplicate(index: number): void {
		const source = this.blocks[index];
		if (!source) return;
		this.pushUndo();
		const copy = $state.snapshot(source) as EditorBlock;
		copy.uid = this.uid();
		this.blocks.splice(index + 1, 0, copy);
		this.#renumber();
		this.markDirty();
		this.expanded.add(copy.uid);
	}

	removeAt(index: number): void {
		const [removed] = this.blocks.splice(index, 1);
		this.#renumber();
		this.markDirty();
		this.selected = null;
		if (removed) this.expanded.delete(removed.uid);
	}

	toggleSelect(index: number): void {
		this.selected = this.selected === index ? null : index;
	}

	// Opening also selects the block so Alt+arrow moves the one you're working on.
	toggleExpand(index: number): void {
		const block = this.blocks[index];
		if (!block) return;
		if (this.expanded.has(block.uid)) {
			this.expanded.delete(block.uid);
		} else {
			this.expanded.add(block.uid);
			this.selected = index;
		}
	}

	isExpanded(uid: string): boolean {
		return this.expanded.has(uid);
	}

	get allExpanded(): boolean {
		return this.blocks.length > 0 && this.blocks.every((b) => this.expanded.has(b.uid));
	}

	expandAll(): void {
		this.expanded = new SvelteSet(this.blocks.map((b) => b.uid));
	}

	collapse(): void {
		this.expanded = new SvelteSet();
	}

	handleKeydown(e: KeyboardEvent, opts: { onSave: () => void; onHelp?: () => void }): void {
		const mod = e.ctrlKey || e.metaKey;
		const el = document.activeElement;
		const typing =
			!!el &&
			(el.tagName === 'INPUT' ||
				el.tagName === 'TEXTAREA' ||
				el.tagName === 'SELECT' ||
				(el as HTMLElement).isContentEditable);
		const dialogOpen = !!document.querySelector('dialog[open]');

		// Ctrl/Cmd+S saves even from a form field (never the browser save dialog).
		if (mod && !e.shiftKey && !e.altKey && e.key.toLowerCase() === 's') {
			e.preventDefault();
			if (dialogOpen) return;
			opts.onSave();
			return;
		}

		if (typing || dialogOpen) return;

		if (e.key === '?' && !mod && !e.altKey && opts.onHelp) {
			e.preventDefault();
			opts.onHelp();
			return;
		}

		if (mod && !e.altKey && e.key.toLowerCase() === 'z') {
			e.preventDefault();
			if (e.shiftKey) this.redo();
			else this.undo();
			return;
		}

		if (e.altKey && !mod && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
			if (this.selected === null) return;
			e.preventDefault();
			this.move(this.selected, e.key === 'ArrowUp' ? -1 : 1);
		}
	}
}
