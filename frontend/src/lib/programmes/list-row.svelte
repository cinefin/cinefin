<script lang="ts">
	import { base } from '$app/paths';
	import {
		CalendarPlus,
		Copy,
		EllipsisVertical,
		Pencil,
		Trash2,
		TriangleAlert,
		Upload
	} from '@lucide/svelte';
	import type { components } from '$lib/api/types.gen';
	import { formatRuntime, relativeTime } from '$lib/format';
	import Button from '$lib/components/ui/Button.svelte';
	import FeatureStack from '$lib/components/FeatureStack.svelte';
	import {
		ACTION_COL,
		CHECK_COL,
		NUM_CELL,
		NUM_CELL_NARROW,
		NUM_CELL_WIDE,
		NAME_COL,
		NUM_GROUP,
		POSTER_COL
	} from './list-columns';

	type Programme = components['schemas']['ProgrammeListItemSchema'];

	interface Props {
		programme: Programme;
		selected: boolean;
		onselect: (p: Programme, on: boolean) => void;
		oncue: (p: Programme) => Promise<void> | void;
		onduplicate: (p: Programme) => Promise<void> | void;
		ondelete: (p: Programme) => void;
	}

	let { programme: p, selected, onselect, oncue, onduplicate, ondelete }: Props = $props();

	const movies = $derived(p.movies ?? []);

	// Suppress the film list only when it's character-identical to the name (a
	// single-film programme auto-named after its film would print it twice).
	const filmList = $derived(movies.map((m) => m.title).join(' · '));
	const showFilmList = $derived(filmList !== '' && filmList !== p.name.trim());

	let menuOpen = $state(false);
	let menuRoot = $state<HTMLDivElement>();

	$effect(() => {
		if (!menuOpen) return;
		const onClick = (e: MouseEvent) => {
			if (menuRoot && !menuRoot.contains(e.target as Node)) menuOpen = false;
		};
		const onKeydown = (e: KeyboardEvent) => {
			if (e.key === 'Escape') menuOpen = false;
		};
		window.addEventListener('click', onClick);
		window.addEventListener('keydown', onKeydown);
		return () => {
			window.removeEventListener('click', onClick);
			window.removeEventListener('keydown', onKeydown);
		};
	});

	// Cue can regenerate a stale playlist, so it reports busy rather than inert.
	let cueing = $state(false);
	async function cue() {
		cueing = true;
		try {
			await oncue(p);
		} finally {
			cueing = false;
		}
	}

	// Hidden until hover/focus (space reserved via ACTION_COL); always on below
	// `md` and on hover-less devices (see the scoped style).
	const actionsVisibility =
		'transition-opacity md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100';

	const menuItem =
		'flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-xs text-muted ' +
		'transition-colors hover:bg-surface-2 hover:text-text';
</script>

<li class="group flex h-14 items-center gap-3 px-3 transition-colors hover:bg-surface-2/40">
	<div class={CHECK_COL}>
		<input
			type="checkbox"
			aria-label="Select {p.name}"
			class="accent-accent"
			checked={selected}
			onchange={(e) => onselect(p, (e.currentTarget as HTMLInputElement).checked)}
		/>
	</div>

	<FeatureStack films={movies} class="{POSTER_COL} justify-end" />

	<div class={NAME_COL}>
		<a
			href="{base}/programmes/{p.id}"
			class="max-w-full shrink-0 truncate text-sm font-medium hover:text-accent"
			title={p.name}
		>
			{p.name}
		</a>
		{#if p.playlist_stale}
			<span
				class="shrink-0 self-center text-warning"
				title="The playlist couldn't be updated automatically - open the programme and regenerate it"
			>
				<TriangleAlert size={13} />
			</span>
		{/if}
		{#if showFilmList}
			<span class="hidden min-w-0 truncate text-xs text-muted md:inline" title={filmList}>
				· {filmList}
			</span>
		{/if}
	</div>

	<div class="{NUM_GROUP} font-mono text-xs text-muted">
		<span class={NUM_CELL} title="Total runtime">{formatRuntime(p.total_runtime)}</span>
		<span class={NUM_CELL_NARROW} title="{p.total_blocks} item{p.total_blocks === 1 ? '' : 's'}">
			{p.total_blocks}
		</span>
		<span class={NUM_CELL_WIDE} title="Created {new Date(p.created_at).toLocaleString()}">
			{new Date(p.created_at).toLocaleDateString()}
		</span>
		{#if p.last_played_at}
			<span class={NUM_CELL} title="Last played {new Date(p.last_played_at).toLocaleString()}">
				{relativeTime(p.last_played_at)}
			</span>
		{:else}
			<span class="{NUM_CELL} text-faint" title="Never played">never</span>
		{/if}
	</div>

	<div
		class="{ACTION_COL} row-actions flex items-center justify-end gap-1.5 {actionsVisibility} {menuOpen
			? 'md:opacity-100'
			: ''}"
	>
		<Button
			size="sm"
			onclick={() => void cue()}
			disabled={cueing}
			title="Cue for playout (doesn't start playback)"
		>
			<Upload size={12} /> Cue
		</Button>
		<Button size="sm" href="{base}/programmes/{p.id}?edit=1" title="Edit the running order">
			<Pencil size={12} /> Edit
		</Button>

		<div class="relative" bind:this={menuRoot}>
			<button
				type="button"
				class="inline-flex h-7 w-7 items-center justify-center rounded-md border border-border-strong
					text-muted transition-colors hover:bg-surface-2 hover:text-text"
				aria-label="More actions for {p.name}"
				aria-haspopup="menu"
				aria-expanded={menuOpen}
				onclick={() => (menuOpen = !menuOpen)}
			>
				<EllipsisVertical size={14} />
			</button>

			{#if menuOpen}
				<div
					class="absolute right-0 z-20 mt-1 w-48 rounded-md border border-border-strong bg-surface-1 py-1"
					role="menu"
				>
					<button
						type="button"
						role="menuitem"
						class={menuItem}
						onclick={() => {
							menuOpen = false;
							void onduplicate(p);
						}}
					>
						<Copy size={13} /> Duplicate
					</button>
					<a
						role="menuitem"
						class={menuItem}
						href="{base}/schedules?new={p.id}"
						onclick={() => (menuOpen = false)}
					>
						<CalendarPlus size={13} /> Schedule a screening
					</a>
					<button
						type="button"
						role="menuitem"
						class="{menuItem} hover:text-danger"
						onclick={() => {
							menuOpen = false;
							ondelete(p);
						}}
					>
						<Trash2 size={13} /> Delete
					</button>
				</div>
			{/if}
		</div>
	</div>
</li>

<style>
	/* Hover-less pointers can't trigger `group-hover`; scoped so it outranks the utility. */
	@media (hover: none) {
		.row-actions {
			opacity: 1;
		}
	}
</style>
