<script lang="ts">
	/**
	 * The user-media tag bar. Filter (default): a chip includes its tag (match any).
	 * Assign (something picked): the same chips tag/untag the selection (all/some/none).
	 * Edit: rename, recolour, delete and add tags, all autosaving. Owns the tag CRUD.
	 */
	import { Check, Minus, Pencil, Plus, X } from '@lucide/svelte';

	import { api, unwrap } from '$lib/api/client';
	import { actMsg } from '$lib/media/actions';
	import { mutate } from '$lib/api/mutate';
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

	// Token-family hues; the first (media cyan) is the default for a new tag.
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

	const PILL =
		'inline-flex items-center gap-[0.35rem] rounded-sm border px-[0.6rem] py-[0.2rem] text-[0.75rem]';
	const CHIP =
		'font-medium transition-[filter,background-color,border-color] duration-120 ease-[ease] enabled:hover:brightness-115 disabled:opacity-60';
	// Edit mode: an inline tag editor pill, its delete/add button, and the palette's swatches.
	const EDIT_PILL =
		'relative inline-flex items-center gap-[0.35rem] rounded-sm border border-border-strong bg-surface-2 py-[0.15rem] pr-[0.3rem] pl-[0.4rem]';
	const PILL_BUTTON =
		'inline-flex size-[1.1rem] items-center justify-center rounded-xs text-faint enabled:hover:bg-surface-3 enabled:hover:text-danger disabled:opacity-40';
	const SWATCH =
		'size-[1.1rem] cursor-pointer rounded-xs border border-white/15 hover:brightness-120';

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

	// "On" (filtering, or on every picked item) is a stronger fill; colourless tags use the surface ladder.
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
		await actMsg('Could not update tags', async () => {
			const res = await unwrap(
				api.POST('/api/v2/media/bulk-tag', { body: { ids, tag: t.name, action } })
			);
			const noun = res.updated === 1 ? 'item' : 'items';
			const verb = action === 'add' ? 'tagged' : 'untagged';
			showToast(`${res.updated} ${noun} ${verb} “${t.name}”`, 'success');
			await onchanged();
		});
		busy = false;
	}

	async function create() {
		const name = newName.trim();
		if (!name || busy) return;
		busy = true;
		await actMsg('Could not create tag', async () => {
			await unwrap(api.POST('/api/v2/media/tags', { body: { name, color: newColor || null } }));
			newName = '';
			paletteFor = null;
			await onchanged();
		});
		busy = false;
	}

	function update(t: Tag, body: { name: string; color: string }, failure: string) {
		void actMsg(failure, async () => {
			const params = { path: { tag_id: t.id } };
			await unwrap(api.PUT('/api/v2/media/tags/{tag_id}', { params, body }));
			if (body.name !== t.name && filter.includes(t.name))
				onfilter(filter.map((n) => (n === t.name ? body.name : n)));
			await onchanged();
		});
	}

	function rename(t: Tag, next: string) {
		const name = next.trim();
		if (name && name !== t.name) update(t, { name, color: t.color || '' }, 'Could not rename tag');
	}

	function recolor(t: Tag, color: string) {
		paletteFor = null;
		if ((t.color ?? '') !== color) update(t, { name: t.name, color }, 'Could not recolour tag');
	}

	async function remove(t: Tag) {
		const msg = `Delete the tag “${t.name}”? It's removed from every item that carries it (the items are kept).`;
		if (!(await confirm(msg, { confirmLabel: 'Delete tag' }))) return;
		await actMsg('Could not delete tag', async () => {
			const params = { path: { tag_id: t.id } };
			await mutate(api.DELETE('/api/v2/media/tags/{tag_id}', { params }));
			if (filter.includes(t.name)) onfilter(filter.filter((n) => n !== t.name));
			await onchanged();
		});
	}

	function onRenameKey(e: KeyboardEvent, t: Tag) {
		if (e.key === 'Enter') (e.currentTarget as HTMLInputElement).blur();
		else if (e.key === 'Escape') (e.currentTarget as HTMLInputElement).value = t.name;
	}
</script>

{#snippet palette(pick: (color: string) => void, clearable = false)}
	<div
		class="absolute top-[calc(100%+4px)] left-0 z-20 flex gap-1 rounded-sm border border-border-strong bg-surface-3 p-[0.35rem]"
	>
		{#each SWATCHES as c (c)}
			<button
				type="button"
				class={SWATCH}
				style="background:{c}"
				aria-label="Set colour"
				onclick={() => pick(c)}
			></button>
		{/each}
		{#if clearable}
			<button
				type="button"
				class="{SWATCH} inline-flex items-center justify-center bg-surface-1 text-muted"
				title="No colour"
				onclick={() => pick('')}
			>
				<X size={11} />
			</button>
		{/if}
	</div>
{/snippet}

<div class="mb-4 flex flex-wrap items-center gap-1.5 border-b border-border pb-3">
	{#if assignMode}
		<span class="mr-1 font-mono text-xs text-accent">{picked.length} selected</span>
		<span class="mr-1 text-xs text-muted">· click a tag to apply</span>
	{/if}

	{#if editing}
		{#each tags as t (t.id)}
			<div class={EDIT_PILL}>
				<button
					type="button"
					class="size-[0.9rem] shrink-0 cursor-pointer rounded-xs border border-border-strong"
					style="background:{t.color || 'transparent'};border-color:{t.color ||
						'var(--color-border-strong)'}"
					title="Recolour"
					aria-label="Recolour {t.name}"
					onclick={() => (paletteFor = paletteFor === t.id ? null : t.id)}
				></button>
				<input
					class="w-28 border-0 bg-transparent text-[0.75rem] text-text outline-none"
					value={t.name}
					aria-label="Rename {t.name}"
					onblur={(e) => rename(t, e.currentTarget.value)}
					onkeydown={(e) => onRenameKey(e, t)}
				/>
				<button type="button" class={PILL_BUTTON} title="Delete tag" onclick={() => void remove(t)}>
					<X size={12} />
				</button>
				{#if paletteFor === t.id}{@render palette((c) => recolor(t, c), true)}{/if}
			</div>
		{/each}

		<div class={EDIT_PILL}>
			<button
				type="button"
				class="size-[0.9rem] shrink-0 cursor-pointer rounded-xs border border-border-strong"
				style="background:{newColor}"
				aria-label="New tag colour"
				onclick={() => (paletteFor = paletteFor === NEW ? null : NEW)}
			></button>
			<input
				class="w-28 border-0 bg-transparent text-[0.75rem] text-text outline-none"
				bind:value={newName}
				placeholder="New tag"
				onkeydown={(e) => {
					if (e.key === 'Enter') void create();
				}}
			/>
			<button
				type="button"
				class={PILL_BUTTON}
				title="Add tag"
				disabled={!newName.trim()}
				onclick={() => void create()}
			>
				<Plus size={12} />
			</button>
			{#if paletteFor === NEW}
				{@render palette((c) => {
					newColor = c;
					paletteFor = null;
				})}
			{/if}
		</div>
	{:else if !tags.length}
		<span class="text-xs text-faint">No tags yet — add one to organise your media.</span>
	{:else}
		{#each tags as t (t.id)}
			{@const st = assignMode ? assignState(t.name) : filter.includes(t.name) ? 'all' : 'none'}
			<button
				type="button"
				class="{PILL} {CHIP} {st === 'some' ? 'border-dashed' : ''}"
				style={chipStyle(t.color, st === 'all')}
				aria-pressed={st !== 'none'}
				disabled={busy}
				onclick={() => onChip(t)}
			>
				{#if assignMode && st === 'all'}<Check
						size={12}
					/>{:else if assignMode && st === 'some'}<Minus size={12} />{/if}
				{t.name}
				<span class="font-mono text-[0.65rem] opacity-70">{t.count ?? 0}</span>
			</button>
		{/each}
	{/if}

	<div class="ml-auto flex items-center gap-1.5">
		{#if assignMode}
			<button
				type="button"
				class="{PILL} border-border bg-surface-2 text-muted hover:bg-surface-3 hover:text-text"
				onclick={onclearpick}>Clear selection</button
			>
		{/if}
		<button
			type="button"
			class="{PILL} border-border bg-surface-2 text-muted hover:bg-surface-3 hover:text-text"
			onclick={() => {
				editing = !editing;
				paletteFor = null;
			}}
		>
			{#if editing}<Check size={12} /> Done{:else}<Pencil size={12} /> Edit tags{/if}
		</button>
	</div>
</div>
