// The state both running-order editors (programme, template) keep around their BlockEditor:
// name and description, the reference lists, loading, validation and saving.
import { type ApiError, toApiError } from '$lib/api/client';
import { showToast } from '$lib/toast.svelte';
import { BlockEditor } from './editor.svelte';
import { loadReferenceLists } from './reference-lists';
import type { EditorBlock, EditorContext, EditorMode, PickedItem } from './types';

export type PickerKind = 'movie' | 'bumper' | 'trailer';

export class EditorSession {
	name = $state('');
	description = $state('');
	/** The id to PUT to: a created programme/template keeps being edited in place. */
	savedId = $state<number | null>(null);
	loading = $state(true);
	loadError = $state<ApiError | null>(null);
	saving = $state(false);
	readonly editor: BlockEditor<{ name: string; description: string }>;
	readonly ctx: EditorContext;
	/** Opens a picker dialog; set by EditorShell, which owns them. */
	pick: (kind: PickerKind) => Promise<PickedItem | null> = async () => null;
	#build: () => Promise<void> = async () => {};

	constructor(mode: EditorMode, id: number | null, name: string, description: string) {
		this.savedId = id;
		this.name = name;
		this.description = description;
		this.editor = new BlockEditor({
			captureMeta: () => ({ name: this.name, description: this.description }),
			restoreMeta: (meta) => {
				this.name = meta.name;
				this.description = meta.description;
			}
		});
		this.ctx = $state({
			mode,
			movies: [],
			programmeMovies: [],
			commands: [],
			tags: [],
			trailerTags: [],
			genres: [],
			certifications: [],
			featureCount: 0,
			pickMovie: mode === 'programme' ? () => this.pick('movie') : undefined,
			pickBumper: () => this.pick('bumper'),
			pickTrailer: () => this.pick('trailer')
		});
	}

	/** Load the reference lists, then `build` the blocks (it resets the editor). */
	async init(build: () => Promise<void>): Promise<void> {
		this.#build = build;
		this.loading = true;
		this.loadError = null;
		try {
			await loadReferenceLists(this.ctx);
			await build();
		} catch (e) {
			this.loadError = toApiError(e);
		} finally {
			this.loading = false;
		}
	}

	retry(): void {
		void this.init(this.#build);
	}

	/** A pick after `add` (which already pushed an undo snapshot): just mutate + mark dirty. */
	picked = (mutate: () => void): void => {
		mutate();
		this.editor.markDirty();
	};

	/** A name and at least one block (else a toast). */
	hasBasics(): boolean {
		const thing = this.ctx.mode;
		if (!this.name.trim()) {
			showToast(`Please enter a ${thing} name`, 'warning');
			return false;
		}
		if (this.editor.blocks.length === 0) {
			showToast(`${thing === 'programme' ? 'Programme' : 'Template'} cannot be empty`, 'warning');
			return false;
		}
		return true;
	}

	/** Flag invalid blocks; false (with a toast) while any needs attention. */
	checkBlocks(errorOf: (block: EditorBlock) => string | null, unit: string): boolean {
		const editor = this.editor;
		const invalid = editor.blocks.filter((b) => errorOf(b)).length;
		editor.showValidation = true;
		if (!invalid) return true;
		editor.scrollTo(editor.blocks.findIndex((b) => errorOf(b)));
		showToast(
			`${invalid} ${unit}${invalid > 1 ? 's need' : ' needs'} attention before saving`,
			'warning'
		);
		return false;
	}

	/** Run a save with the busy flag; a failure toasts "Error saving <thing>: …". */
	async save(run: () => Promise<void>): Promise<void> {
		this.saving = true;
		try {
			await run();
		} catch (e) {
			showToast(
				`Error saving ${this.ctx.mode}: ` + (e instanceof Error ? e.message : 'Unknown error'),
				'error'
			);
		} finally {
			this.saving = false;
		}
	}

	/** After a successful save. */
	clean(): void {
		this.editor.dirty = false;
		this.editor.showValidation = false;
	}
}
