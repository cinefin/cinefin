<script lang="ts">
	import { Dices, Plus, TriangleAlert, X } from '@lucide/svelte';
	import { api, unwrap } from '$lib/api/client';
	import Button from '$lib/components/ui/Button.svelte';
	import Dialog from '$lib/components/ui/Dialog.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import { itemTypeDisplay } from '$lib/item-types';
	import type { RandomSlot } from './create-types';

	interface Props {
		open?: boolean;
		/** Pre-fill — the library's active filters, or the slot being replaced. */
		initial?: Partial<RandomSlot> | null;
		confirmLabel?: string;
		onconfirm: (slot: RandomSlot) => void;
	}

	let {
		open = $bindable(false),
		initial = null,
		confirmLabel = 'Use pick',
		onconfirm
	}: Props = $props();

	const type = itemTypeDisplay('random_movie');

	// Options loaded once; a failure just leaves the pick unfiltered.
	let genres = $state<{ id: number; name: string }[]>([]);
	let certifications = $state<string[]>([]);
	let optionsLoaded = false;
	$effect(() => {
		if (!open || optionsLoaded) return;
		optionsLoaded = true;
		void (async () => {
			try {
				const [g, r] = await Promise.all([
					unwrap(api.GET('/api/v2/movies/genres')),
					unwrap(api.GET('/api/v2/movies/ratings-options'))
				]);
				genres = g ?? [];
				certifications = r?.ratings ?? [];
			} catch (e) {
				console.error('Could not load the random-pick filter options', e);
			}
		})();
	});

	let genreIds = $state<number[]>([]);
	let certification = $state('');
	let range = $state({ year_from: '', year_to: '', runtime_from: '', runtime_to: '' });
	let addGenre = $state('');
	let pendingGenreNames = $state<string[]>([]);

	/** Reset to `initial` each time the dialog opens (never mid-edit). */
	let wasOpen = false;
	$effect(() => {
		if (open === wasOpen) return;
		wasOpen = open;
		if (!open) return;
		const n = (v: number | null | undefined) => (v ? String(v) : '');
		genreIds = [...(initial?.genre_ids ?? [])];
		// A caller with only names (the library) gets them matched once genres load.
		pendingGenreNames = genreIds.length ? [] : [...(initial?.genre_names ?? [])];
		certification = initial?.certification ?? '';
		range = {
			year_from: n(initial?.year_from),
			year_to: n(initial?.year_to),
			runtime_from: n(initial?.runtime_from),
			runtime_to: n(initial?.runtime_to)
		};
		addGenre = '';
	});

	$effect(() => {
		if (!pendingGenreNames.length || !genres.length) return;
		const wanted = pendingGenreNames.map((n) => n.toLowerCase());
		genreIds = genres.filter((g) => wanted.includes(g.name.toLowerCase())).map((g) => g.id);
		pendingGenreNames = [];
	});

	const chosenGenres = $derived(
		genreIds.map((id) => genres.find((g) => g.id === id)).filter((g) => !!g)
	);
	const remainingGenres = $derived(genres.filter((g) => !genreIds.includes(g.id)));

	function pickGenre(value: string): void {
		const id = parseInt(value, 10);
		if (!Number.isNaN(id) && !genreIds.includes(id)) genreIds = [...genreIds, id];
		addGenre = '';
	}

	function dropGenre(id: number): void {
		genreIds = genreIds.filter((g) => g !== id);
	}

	const num = (v: string): number | null => {
		const n = parseInt(v, 10);
		return Number.isNaN(n) ? null : n;
	};

	const draft = $derived<RandomSlot>({
		kind: 'random',
		id: 0,
		label: null,
		genre_ids: genreIds,
		genre_names: chosenGenres.map((g) => g.name),
		certification: certification || null,
		year_from: num(range.year_from),
		year_to: num(range.year_to),
		runtime_from: num(range.runtime_from),
		runtime_to: num(range.runtime_to)
	});

	// Live match count: debounced, sequence-guarded, same filters as the backend's
	// random query. A failed count leaves the last good number.
	let matching = $state<number | null>(null);
	let counting = $state(false);
	let countSeq = 0;

	$effect(() => {
		if (!open) return;
		const q: Record<string, string | number> = { per_page: 1 };
		if (draft.genre_names.length) q.genre = draft.genre_names.join(',');
		if (draft.certification) q.certification = draft.certification;
		if (draft.year_from) q.year_from = draft.year_from;
		if (draft.year_to) q.year_to = draft.year_to;
		if (draft.runtime_from) q.runtime_from = draft.runtime_from;
		if (draft.runtime_to) q.runtime_to = draft.runtime_to;

		const seq = ++countSeq;
		counting = true;
		const timer = setTimeout(async () => {
			try {
				const data = await unwrap(api.GET('/api/v2/movies/list', { params: { query: q } }));
				if (seq !== countSeq) return;
				matching = data?.pagination?.total ?? 0;
			} catch (e) {
				console.error('Could not count matching movies', e);
			} finally {
				if (seq === countSeq) counting = false;
			}
		}, 250);
		return () => clearTimeout(timer);
	});

	function confirm(): void {
		onconfirm({ ...draft, id: Date.now() });
		open = false;
	}

	const fieldLabel = 'w-24 shrink-0 pt-2 text-xs text-muted';
	const row = 'flex flex-wrap items-start gap-2';
	const rangeInput = 'h-8 w-24 text-xs';
</script>

<Dialog bind:open title="Random movie" size="xl">
	<div class="space-y-3">
		<p class="text-sm text-muted">
			The movie is drawn when the playlist is generated, from everything matching these filters.
			Leave them empty for any movie in the library.
		</p>

		<div class={row}>
			<span class={fieldLabel}>Genres</span>
			<div class="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
				{#each chosenGenres as genre (genre.id)}
					<span
						class="inline-flex items-center gap-1 rounded-sm border border-border-strong
							bg-surface-2 py-1 pr-1 pl-2 text-xs"
					>
						{genre.name}
						<button
							type="button"
							class="rounded-sm p-0.5 text-faint hover:text-danger"
							aria-label="Remove {genre.name}"
							onclick={() => dropGenre(genre.id)}
						>
							<X size={12} />
						</button>
					</span>
				{/each}
				{#if remainingGenres.length}
					<label class="inline-flex items-center gap-1 text-xs text-faint">
						<Plus size={12} aria-hidden="true" />
						<span class="sr-only">Add a genre</span>
						<Select
							value={addGenre}
							class="h-8 text-xs"
							onchange={(e) => pickGenre((e.currentTarget as HTMLSelectElement).value)}
						>
							<option value="">{chosenGenres.length ? 'Add genre…' : 'Any genre'}</option>
							{#each remainingGenres as genre (genre.id)}
								<option value={String(genre.id)}>{genre.name}</option>
							{/each}
						</Select>
					</label>
				{/if}
			</div>
		</div>
		{#if chosenGenres.length > 1}
			<p class="pl-26 text-xs text-faint">A movie must match every genre listed.</p>
		{/if}

		<div class={row}>
			<span class={fieldLabel}>Certificate</span>
			<Select bind:value={certification} class="h-8 text-xs">
				<option value="">Any certificate</option>
				{#each certifications as cert (cert)}
					<option value={cert}>{cert}</option>
				{/each}
			</Select>
		</div>

		{#each [['Release year', 'year'], ['Runtime', 'runtime']] as const as [label, key] (key)}
			<div class={row}>
				<span class={fieldLabel}>{label}</span>
				<div class="flex items-center gap-2">
					<Input
						type="number"
						bind:value={range[`${key}_from`]}
						placeholder="From"
						class={rangeInput}
					/>
					<span class="text-faint" aria-hidden="true">-</span>
					<Input
						type="number"
						bind:value={range[`${key}_to`]}
						placeholder="To"
						class={rangeInput}
					/>
					{#if key === 'runtime'}<span class="text-xs text-faint">minutes</span>{/if}
				</div>
			</div>
		{/each}

		<p
			class="flex items-center gap-1.5 border-t border-border pt-3 font-mono text-xs
				{matching === 0 ? 'text-danger' : 'text-muted'}"
			aria-live="polite"
		>
			{#if matching === null || counting}
				<Dices size={12} class={type.classes.icon} /> Counting movies…
			{:else if matching === 0}
				<TriangleAlert size={12} /> No movies match - the playlist would skip this slot
			{:else}
				<Dices size={12} class={type.classes.icon} />
				{matching}
				{matching === 1 ? 'movie matches' : 'movies match'}
			{/if}
		</p>
	</div>

	{#snippet footer()}
		<Button onclick={() => (open = false)}>Cancel</Button>
		<Button variant="primary" disabled={matching === 0} onclick={confirm}>
			<Dices size={14} />
			{confirmLabel}
		</Button>
	{/snippet}
</Dialog>
