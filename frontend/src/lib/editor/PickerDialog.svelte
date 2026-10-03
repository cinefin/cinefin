<script lang="ts">
	import { Check, Clapperboard, Film, Images, Plus } from '@lucide/svelte';
	import { api, unwrap } from '$lib/api/client';
	import { unwrapLoose } from '$lib/jobs';
	import { showToast } from '$lib/toast.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Dialog from '$lib/components/ui/Dialog.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import type { PickedItem } from './types';

	type Kind = 'movie' | 'bumper' | 'trailer';

	interface Props {
		kind: Kind;
		mode?: 'single' | 'multi';
		isSelected?: (item: PickedItem) => boolean;
		onadd?: (item: PickedItem) => void | Promise<void>;
	}

	let { kind, mode = 'single', isSelected, onadd }: Props = $props();

	const DEFAULTS = {
		movie: {
			title: 'Choose a movie',
			placeholder: 'Search by title, director or description…',
			icon: Film,
			none: ['No movies match your search', 'sync a media source first'],
			noun: 'No movies'
		},
		bumper: {
			title: 'Choose user media',
			placeholder: 'Search user media by title…',
			icon: Images,
			none: ['No user media matches your search', 'upload some on the Media page'],
			noun: 'No user media'
		},
		trailer: {
			title: 'Choose a trailer',
			placeholder: 'Search trailers by title…',
			icon: Clapperboard,
			none: ['No trailers match your search or filters', 'fetch some on the Trailers page'],
			noun: 'No trailers'
		}
	} satisfies Record<Kind, unknown>;

	let open = $state(false);
	let searchInput = $state('');
	let genre = $state('');
	let certification = $state('');
	let results = $state<PickedItem[]>([]);
	let loading = $state(false);
	let searchError = $state(false);
	let genreOptions = $state<string[]>([]);
	let certOptions = $state<string[]>([]);
	let facetsLoaded = false;
	let seq = 0;
	let debounceTimer: ReturnType<typeof setTimeout> | undefined;
	let addedIds = $state<Set<number>>(new Set());
	let addingId = $state<number | null>(null);

	let resolver: ((item: PickedItem | null) => void) | null = null;

	export function pick(): Promise<PickedItem | null> {
		openDialog();
		return new Promise((resolve) => {
			resolver = resolve;
		});
	}

	export function show(): void {
		openDialog();
	}

	function openDialog(): void {
		searchInput = '';
		genre = '';
		certification = '';
		addedIds = new Set();
		open = true;
		void runSearch();
	}

	function settle(item: PickedItem | null): void {
		const resolve = resolver;
		resolver = null;
		resolve?.(item);
	}

	$effect(() => {
		if (!open && resolver) settle(null);
	});

	function onSearchInput(): void {
		clearTimeout(debounceTimer);
		debounceTimer = setTimeout(() => void runSearch(), 250);
	}

	async function runSearch(): Promise<void> {
		const mySeq = ++seq;
		loading = true;
		searchError = false;
		try {
			let items: PickedItem[];
			if (kind === 'movie') {
				const data = await unwrap(
					api.GET('/api/v2/movies/list', {
						params: {
							query: {
								search: searchInput.trim() || null,
								genre: genre || null,
								certification: certification || null,
								per_page: 30,
								sort: 'title',
								order: 'asc'
							}
						}
					})
				);
				if (!facetsLoaded) {
					genreOptions = data.filters.genres;
					certOptions = data.filters.certifications;
					facetsLoaded = true;
				}
				items = data.items;
			} else if (kind === 'bumper') {
				const data = await unwrap(
					api.GET('/api/v2/media/list', {
						params: { query: { search: searchInput.trim() || null, per_page: 30 } }
					})
				);
				items = data.media;
			} else {
				// Trailer library response is untyped in OpenAPI; shape mirrored from trailer_ninja.trailer_library.
				const data = await unwrapLoose<{
					trailers: {
						id: number;
						title: string;
						year: number | null;
						duration: number | null;
						content_rating: string | null;
					}[];
					facets: { ratings: string[]; genres: string[] };
				}>(
					api.GET('/api/v2/trailers/library', {
						params: {
							query: {
								q: searchInput.trim(),
								genre,
								rating: certification,
								limit: 30,
								sort: 'title'
							}
						}
					})
				);
				if (!facetsLoaded) {
					genreOptions = data.facets.genres;
					certOptions = data.facets.ratings;
					facetsLoaded = true;
				}
				items = data.trailers.map((t) => ({
					id: t.id,
					title: t.title,
					year: t.year,
					duration: t.duration,
					content_rating: t.content_rating
				}));
			}
			if (mySeq !== seq) return; // superseded by a newer search
			results = items;
		} catch (e) {
			if (mySeq !== seq) return;
			console.error('PickerDialog: search failed:', e);
			searchError = true;
		} finally {
			if (mySeq === seq) loading = false;
		}
	}

	function emptyText(): string {
		const { none, noun } = DEFAULTS[kind];
		return searchInput.trim() || genre || certification
			? none[0]
			: `${noun} in your library yet - ${none[1]}`;
	}

	// Each kind's rows carry only their own fields (movies: runtime/director; the rest: duration).
	function rowMeta(item: PickedItem): string {
		const secs = Math.round(item.duration ?? 0);
		return [
			item.year,
			item.runtime ? `${item.runtime} min` : null,
			item.director,
			secs ? `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, '0')}` : null
		]
			.filter(Boolean)
			.join(' • ');
	}

	function pickRow(item: PickedItem): void {
		settle(item);
		open = false;
	}

	async function addRow(item: PickedItem): Promise<void> {
		if (!onadd || addingId !== null) return;
		addingId = item.id;
		try {
			await onadd(item);
			addedIds = new Set([...addedIds, item.id]);
		} catch (e) {
			console.error('PickerDialog: add failed:', e);
			showToast(e instanceof Error ? e.message : 'Failed to add', 'error');
		} finally {
			addingId = null;
		}
	}

	const rowAdded = (item: PickedItem) => addedIds.has(item.id) || !!isSelected?.(item);

	const Icon = $derived(DEFAULTS[kind].icon);
</script>

<Dialog bind:open title={mode === 'multi' ? 'Add movies' : DEFAULTS[kind].title} size="2xl">
	<div class="space-y-3">
		<div class="flex flex-wrap gap-2">
			<Input
				type="search"
				placeholder={DEFAULTS[kind].placeholder}
				bind:value={searchInput}
				oninput={onSearchInput}
				class="min-w-48 flex-1"
			/>
			{#if kind !== 'bumper'}
				<Select bind:value={genre} onchange={() => void runSearch()} class="w-36">
					<option value="">All genres</option>
					{#each genreOptions as g (g)}<option value={g}>{g}</option>{/each}
				</Select>
				<Select bind:value={certification} onchange={() => void runSearch()} class="w-32">
					<option value="">All ratings</option>
					{#each certOptions as c (c)}<option value={c}>{c}</option>{/each}
				</Select>
			{/if}
		</div>

		<div class="max-h-96 overflow-y-auto rounded-md border border-border">
			{#if loading}
				<Spinner label="Searching…" size="sm" />
			{:else if searchError}
				<EmptyState icon={Icon} title="Could not search the library" compact />
			{:else if !results.length}
				<EmptyState icon={Icon} title={emptyText()} compact />
			{:else}
				<ul class="divide-y divide-border">
					{#snippet rowContent(item: PickedItem)}
						<div
							class="flex h-12 w-8 shrink-0 items-center justify-center overflow-hidden rounded-sm bg-surface-3 text-faint"
						>
							{#if item.thumbnail_url || item.screenshot_url}
								<img
									src={item.thumbnail_url || item.screenshot_url}
									alt=""
									loading="lazy"
									class="h-full w-full object-cover"
								/>
							{:else}
								<Icon size={14} />
							{/if}
						</div>
						<div class="min-w-0 flex-1">
							<p class="flex items-center gap-2 truncate text-sm">
								<span class="truncate">{item.title}</span>
								{#if item.certification || item.content_rating}
									<span
										class="shrink-0 rounded-sm border border-border-strong px-1 py-px font-mono text-[0.65rem] text-muted"
									>
										{item.certification || item.content_rating}
									</span>
								{/if}
							</p>
							{#if rowMeta(item)}
								<p class="truncate text-xs text-muted">{rowMeta(item)}</p>
							{/if}
						</div>
					{/snippet}
					{#each results as item (item.id)}
						{@const added = mode === 'multi' && rowAdded(item)}
						<li>
							{#if mode === 'single'}
								<button
									type="button"
									class="flex w-full cursor-pointer items-center gap-3 px-3 py-2 text-left hover:bg-surface-2"
									onclick={() => pickRow(item)}
								>
									{@render rowContent(item)}
								</button>
							{:else}
								<div
									class="flex w-full items-center gap-3 px-3 py-2 text-left {added
										? 'opacity-60'
										: ''}"
								>
									{@render rowContent(item)}
									<Button
										size="sm"
										disabled={added || addingId === item.id}
										onclick={() => void addRow(item)}
									>
										{#if added}<Check size={12} /> Added{:else}<Plus size={12} /> Add{/if}
									</Button>
								</div>
							{/if}
						</li>
					{/each}
				</ul>
			{/if}
		</div>
	</div>

	{#snippet footer()}
		<Button onclick={() => (open = false)}>{mode === 'multi' ? 'Done' : 'Cancel'}</Button>
	{/snippet}
</Dialog>
