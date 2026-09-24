<script lang="ts">
	/**
	 * The user-media tag bar — one persistent, colour-coded surface that does the
	 * three jobs tags used to scatter across a filter dropdown, a free-text bulk
	 * box and a modal:
	 *
	 *   • Filter (default): click a chip to include its tag (match ANY / OR).
	 *   • Assign (something selected): the SAME chips tag/untag the selection —
	 *     a chip reads all / some / none of the picked items and toggles.
	 *   • Edit: rename inline, recolour from a curated swatch palette, delete,
	 *     and add new tags — all autosaving, no per-row Save.
	 *
	 * The bar owns the tag CRUD + bulk-tag calls; the page passes the facets, the
	 * active filter, the picked items, and a reload callback.
	 */
	import { Check, Minus, Pencil, Plus, X } from '@lucide/svelte';

	import { api, toApiError, unwrap } from '$lib/api/client';
	import type { components } from '$lib/api/types.gen';
	import { showToast } from '$lib/toast.svelte';

	type Tag = components['schemas']['TagSchema'];
	type MediaItem = components['schemas']['MediaItemSchema'];

	interface Props {
		tags: Tag[];
		/** Active filter tag names. */
		filter: string[];
		onfilter: (names: string[]) => void;
		/** Currently selected media items (drives assign mode + state). */
		picked: MediaItem[];
		/** Reload the list after any mutation (refreshes facets, counts, item tags). */
		onchanged: () => Promise<void> | void;
		onclearpick: () => void;
		/** Awaitable confirm owned by the page (its ConfirmDialog instance). */
		confirm: (msg: string, opts?: { confirmLabel?: string }) => Promise<boolean>;
	}
	let { tags, filter, onfilter, picked, onchanged, onclearpick, confirm }: Props = $props();

	// On-brand swatches (the design-token family hues), readable on the dark
	// surface. First is the media-family cyan — the sensible default for a bumper.
	const SWATCHES = [
		'#22D3EE',
		'#3A7BFF',
		'#A78BFA',
		'#F5C451',
		'#FB7185',
		'#34D399',
		'#F59E0B',
		'#94A3B8'
	];
	const NEW = -1; // palette sentinel for the new-tag pill

	let editing = $state(false);
	const assignMode = $derived(picked.length > 0 && !editing);

	let busy = $state(false);
	let newName = $state('');
	let newColor = $state(SWATCHES[0]);
	let paletteFor = $state<number | null>(null); // tag id (or NEW) whose palette is open

	function assignState(name: string): 'all' | 'some' | 'none' {
		const n = picked.filter((m) => m.tags.some((t) => t.name === name)).length;
		return n === 0 ? 'none' : n === picked.length ? 'all' : 'some';
	}

	// Tag chips carry their own colour; "on" (active filter, or fully-applied to
	// the selection) reads as a stronger fill. Colourless tags fall back to the
	// neutral surface ladder.
	function chipStyle(color: string | null | undefined, on: boolean): string {
		if (!color) {
			return on
				? 'background:var(--color-surface-3);border-color:var(--color-border-strong);color:var(--color-text)'
				: 'background:var(--color-surface-2);border-color:var(--color-border);color:var(--color-muted)';
		}
		return on
			? `background:${color}3d;border-color:${color};color:#fff`
			: `background:${color}1f;border-color:${color}66;color:${color}`;
	}

	function onChip(t: Tag) {
		if (editing) return;
		if (assignMode) void toggleAssign(t);
		else
			onfilter(filter.includes(t.name) ? filter.filter((n) => n !== t.name) : [...filter, t.name]);
	}

	async function toggleAssign(t: Tag) {
		if (busy) return;
		const ids = picked.map((m) => m.id);
		const action = assignState(t.name) === 'all' ? 'remove' : 'add';
		busy = true;
		try {
			const res = await unwrap(
				api.POST('/api/v2/media/bulk-tag', { body: { ids, tag: t.name, action } })
			);
			const noun = res.updated === 1 ? 'item' : 'items';
			showToast(
				`${res.updated} ${noun} ${action === 'add' ? 'tagged' : 'untagged'} “${t.name}”`,
				'success'
			);
			await onchanged();
		} catch (e) {
			showToast(toApiError(e).message || 'Could not update tags', 'error');
		} finally {
			busy = false;
		}
	}

	async function create() {
		const name = newName.trim();
		if (!name || busy) return;
		busy = true;
		try {
			await unwrap(api.POST('/api/v2/media/tags', { body: { name, color: newColor || null } }));
			newName = '';
			paletteFor = null;
			await onchanged();
		} catch (e) {
			showToast(toApiError(e).message || 'Could not create tag', 'error');
		} finally {
			busy = false;
		}
	}

	async function rename(t: Tag, next: string) {
		const name = next.trim();
		if (!name || name === t.name) return;
		try {
			await unwrap(
				api.PUT('/api/v2/media/tags/{tag_id}', {
					params: { path: { tag_id: t.id } },
					body: { name, color: t.color || '' }
				})
			);
			if (filter.includes(t.name)) onfilter(filter.map((n) => (n === t.name ? name : n)));
			await onchanged();
		} catch (e) {
			showToast(toApiError(e).message || 'Could not rename tag', 'error');
		}
	}

	async function recolor(t: Tag, color: string) {
		paletteFor = null;
		if ((t.color ?? '') === color) return;
		try {
			await unwrap(
				api.PUT('/api/v2/media/tags/{tag_id}', {
					params: { path: { tag_id: t.id } },
					body: { name: t.name, color }
				})
			);
			await onchanged();
		} catch (e) {
			showToast(toApiError(e).message || 'Could not recolour tag', 'error');
		}
	}

	async function remove(t: Tag) {
		if (
			!(await confirm(
				`Delete the tag “${t.name}”? It's removed from every item that carries it (the items are kept).`,
				{ confirmLabel: 'Delete tag' }
			))
		)
			return;
		try {
			const res = await api.DELETE('/api/v2/media/tags/{tag_id}', {
				params: { path: { tag_id: t.id } }
			});
			if (res.error !== undefined) throw toApiError(res.error, res.response);
			if (filter.includes(t.name)) onfilter(filter.filter((n) => n !== t.name));
			await onchanged();
		} catch (e) {
			showToast(toApiError(e).message || 'Could not delete tag', 'error');
		}
	}

	function onRenameKey(e: KeyboardEvent, t: Tag) {
		if (e.key === 'Enter') (e.currentTarget as HTMLInputElement).blur();
		else if (e.key === 'Escape') (e.currentTarget as HTMLInputElement).value = t.name;
	}
</script>

<div class="mb-4 flex flex-wrap items-center gap-1.5 border-b border-border pb-3">
	{#if assignMode}
		<span class="mr-1 font-mono text-xs text-accent">{picked.length} selected</span>
		<span class="mr-1 text-xs text-muted">· click a tag to apply</span>
	{/if}

	{#if editing}
		{#each tags as t (t.id)}
			<div class="tag-edit">
				<button
					type="button"
					class="tag-swatch"
					style="background:{t.color || 'transparent'};border-color:{t.color ||
						'var(--color-border-strong)'}"
					title="Recolour"
					aria-label="Recolour {t.name}"
					onclick={() => (paletteFor = paletteFor === t.id ? null : t.id)}
				></button>
				<input
					class="tag-name"
					value={t.name}
					aria-label="Rename {t.name}"
					onblur={(e) => void rename(t, (e.currentTarget as HTMLInputElement).value)}
					onkeydown={(e) => onRenameKey(e, t)}
				/>
				<button type="button" class="tag-del" title="Delete tag" onclick={() => void remove(t)}>
					<X size={12} />
				</button>
				{#if paletteFor === t.id}
					<div class="palette">
						{#each SWATCHES as c (c)}
							<button
								type="button"
								class="sw"
								style="background:{c}"
								aria-label="Set colour"
								onclick={() => void recolor(t, c)}
							></button>
						{/each}
						<button
							type="button"
							class="sw sw-none"
							title="No colour"
							onclick={() => void recolor(t, '')}
						>
							<X size={11} />
						</button>
					</div>
				{/if}
			</div>
		{/each}

		<div class="tag-edit">
			<button
				type="button"
				class="tag-swatch"
				style="background:{newColor}"
				aria-label="New tag colour"
				onclick={() => (paletteFor = paletteFor === NEW ? null : NEW)}
			></button>
			<input
				class="tag-name"
				bind:value={newName}
				placeholder="New tag"
				onkeydown={(e) => {
					if (e.key === 'Enter') void create();
				}}
			/>
			<button
				type="button"
				class="tag-del"
				title="Add tag"
				disabled={!newName.trim()}
				onclick={() => void create()}
			>
				<Plus size={12} />
			</button>
			{#if paletteFor === NEW}
				<div class="palette">
					{#each SWATCHES as c (c)}
						<button
							type="button"
							class="sw"
							style="background:{c}"
							aria-label="Set colour"
							onclick={() => {
								newColor = c;
								paletteFor = null;
							}}
						></button>
					{/each}
				</div>
			{/if}
		</div>
	{:else if !tags.length}
		<span class="text-xs text-faint">No tags yet — add one to organise your media.</span>
	{:else}
		{#each tags as t (t.id)}
			{@const st = assignMode ? assignState(t.name) : filter.includes(t.name) ? 'all' : 'none'}
			<button
				type="button"
				class="chip {st === 'some' ? 'chip-partial' : ''}"
				style={chipStyle(t.color, st === 'all')}
				aria-pressed={st !== 'none'}
				disabled={busy}
				onclick={() => onChip(t)}
			>
				{#if assignMode && st === 'all'}<Check
						size={12}
					/>{:else if assignMode && st === 'some'}<Minus size={12} />{/if}
				{t.name}
				<span class="count">{t.count ?? 0}</span>
			</button>
		{/each}
	{/if}

	<div class="ml-auto flex items-center gap-1.5">
		{#if assignMode}
			<button type="button" class="ghost" onclick={onclearpick}>Clear selection</button>
		{/if}
		<button
			type="button"
			class="ghost"
			onclick={() => {
				editing = !editing;
				paletteFor = null;
			}}
		>
			{#if editing}<Check size={12} /> Done{:else}<Pencil size={12} /> Edit tags{/if}
		</button>
	</div>
</div>

<style>
	.chip {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		border: 1px solid;
		border-radius: var(--radius-sm);
		padding: 0.2rem 0.6rem;
		font-size: 0.75rem;
		font-weight: 500;
		transition:
			filter 0.12s ease,
			background-color 0.12s ease,
			border-color 0.12s ease;
	}
	.chip:hover:not(:disabled) {
		filter: brightness(1.15);
	}
	.chip:disabled {
		opacity: 0.6;
	}
	.chip .count {
		font-family: var(--font-mono, monospace);
		font-size: 0.65rem;
		opacity: 0.7;
	}
	/* Partially-applied (assign mode): a dashed border reads "some, not all". */
	.chip-partial {
		border-style: dashed;
	}

	.ghost {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		background: var(--color-surface-2);
		color: var(--color-muted);
		padding: 0.2rem 0.6rem;
		font-size: 0.75rem;
	}
	.ghost:hover {
		color: var(--color-text);
		background: var(--color-surface-3);
	}

	/* Edit mode: an inline tag editor pill. */
	.tag-edit {
		position: relative;
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-sm);
		background: var(--color-surface-2);
		padding: 0.15rem 0.3rem 0.15rem 0.4rem;
	}
	.tag-swatch {
		height: 0.9rem;
		width: 0.9rem;
		flex-shrink: 0;
		border: 1px solid var(--color-border-strong);
		border-radius: 2px;
		cursor: pointer;
	}
	.tag-name {
		width: 7rem;
		border: 0;
		background: transparent;
		color: var(--color-text);
		font-size: 0.75rem;
		outline: none;
	}
	.tag-del {
		display: inline-flex;
		height: 1.1rem;
		width: 1.1rem;
		align-items: center;
		justify-content: center;
		border-radius: 2px;
		color: var(--color-faint);
	}
	.tag-del:hover:not(:disabled) {
		color: var(--color-danger);
		background: var(--color-surface-3);
	}
	.tag-del:disabled {
		opacity: 0.4;
	}

	/* Swatch palette popover under an editor pill. */
	.palette {
		position: absolute;
		top: calc(100% + 4px);
		left: 0;
		z-index: 20;
		display: flex;
		gap: 0.25rem;
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-sm);
		background: var(--color-surface-3);
		padding: 0.35rem;
	}
	.sw {
		height: 1.1rem;
		width: 1.1rem;
		border: 1px solid rgb(255 255 255 / 0.15);
		border-radius: 2px;
		cursor: pointer;
	}
	.sw:hover {
		filter: brightness(1.2);
	}
	.sw-none {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		background: var(--color-surface-1);
		color: var(--color-muted);
	}
</style>
