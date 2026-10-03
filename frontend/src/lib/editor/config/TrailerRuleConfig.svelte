<script lang="ts">
	import { Dices, Film, Plus } from '@lucide/svelte';
	import { api, unwrap } from '$lib/api/client';
	import StatusLamp from '$lib/components/StatusLamp.svelte';
	import ConfigField from '../ConfigField.svelte';
	import ConfigForm from '../ConfigForm.svelte';
	import ConfigSelect from '../ConfigSelect.svelte';
	import GenreChips from '../GenreChips.svelte';
	import NumberInput from '../NumberInput.svelte';
	import { featureOptions, idOptions, type EditorBlock, type ConfigProps } from '../types';

	let { block, ctx, commit }: ConfigProps = $props();

	type Content = EditorBlock['content'];
	const set = <K extends keyof Content>(field: K, value: Content[K]) =>
		commit(() => (block.content[field] = value));

	const isBoundToRandom = $derived(
		ctx.mode === 'programme' && block.content.bound_to_block_order != null
	);

	const refMovie = $derived(
		block.content.reference_movie_id
			? ctx.movies.find((m) => m.id === block.content.reference_movie_id)
			: null
	);

	const SEED_YEARS = 5;
	type MovieDetail = {
		genres?: number[] | null;
		certification?: string | null;
		year?: number | null;
	};
	let refGenreIds = $state<number[]>([]);
	let refCert = $state('');
	let refYear = $state<number | null>(null);
	let lastSeededId = $state<number | null>(null);

	function seedRef(m: MovieDetail | null, id: number | null): void {
		refGenreIds = m?.genres ?? [];
		refCert = m?.certification ?? '';
		refYear = m?.year ?? null;
		lastSeededId = id;
	}

	const fetchMovie = (id: number) =>
		unwrap(api.GET('/api/v2/movies/{movie_id}', { params: { path: { movie_id: id } } }));

	async function pickReference() {
		const picked = await ctx.pickMovie?.();
		if (!picked) return;
		try {
			const m = await fetchMovie(picked.id);
			commit(() => {
				block.content.reference_movie_id = picked.id;
				block.content.genre_ids = m.genres ?? [];
				block.content.certificate_ceiling = m.certification ?? '';
				block.content.year_from = m.year ? m.year - SEED_YEARS : null;
				block.content.year_to = m.year ? m.year + SEED_YEARS : null;
			});
			// Seed the chips from this detail so the $effect below doesn't refetch it.
			seedRef(m, picked.id);
		} catch {
			set('reference_movie_id', picked.id);
		}
	}

	$effect(() => {
		const id = block.content.reference_movie_id;
		if (ctx.mode !== 'programme' || !id) {
			seedRef(null, null);
			return;
		}
		if (id === lastSeededId) return;
		let cancelled = false;
		fetchMovie(id)
			.then((m) => !cancelled && seedRef(m, id))
			.catch(() => {});
		return () => {
			cancelled = true;
		};
	});

	const selectedGenreIds = $derived(block.content.genre_ids ?? []);
	const genreName = (id: number) => ctx.genres.find((g) => g.id === id)?.name ?? String(id);
	const seedGenres = $derived(refGenreIds.filter((id) => !selectedGenreIds.includes(id)));

	function seedFromReferenceYear() {
		if (refYear == null) return;
		commit(() => {
			block.content.year_from = refYear! - SEED_YEARS;
			block.content.year_to = refYear! + SEED_YEARS;
		});
	}

	type Match = { text: string; colour: 'green' | 'amber' | 'red' | 'neutral'; pending?: boolean };
	let match = $state<Match | null>(null);
	let matchSeq = 0;
	$effect(() => {
		if (ctx.mode !== 'programme' || isBoundToRandom) {
			match = null;
			return;
		}
		// Read everything reactive up front so the effect re-runs on any change.
		const c = block.content;
		const count = c.count || 3;
		const query: Record<string, string | number> = { count };
		if (c.reference_movie_id) query.movie_id = c.reference_movie_id;
		if (selectedGenreIds.length) query.genre_ids = selectedGenreIds.join(',');
		if (c.certificate_ceiling) query.certificate_ceiling = c.certificate_ceiling;
		if (c.year_from != null) query.year_from = c.year_from;
		if (c.year_to != null) query.year_to = c.year_to;
		if (c.trailer_tag_id) query.tag_id = c.trailer_tag_id;

		const seq = ++matchSeq;
		match = { text: 'Checking…', colour: 'neutral', pending: true };
		const timer = setTimeout(async () => {
			try {
				const data = await unwrap(api.GET('/api/v2/trailers/match-test', { params: { query } }));
				if (seq !== matchSeq) return;
				const n = data.matched;
				if (n === 0) match = { text: 'No trailers match — nothing will play here', colour: 'red' };
				else if (n >= count)
					match = { text: `${n} trailer${n === 1 ? '' : 's'} match`, colour: 'green' };
				else
					match = {
						text: `Only ${n} of ${count} match — the rest of the slot stays empty`,
						colour: 'amber'
					};
			} catch {
				if (seq === matchSeq) match = null;
			}
		}, 300);
		return () => clearTimeout(timer);
	});

	const MATCH_ON = [
		{ key: 'match_genres', label: 'Genre', fallback: true },
		{ key: 'match_certification', label: 'Rating', fallback: true },
		{ key: 'match_year', label: 'Year', fallback: false }
	] as const;

	const chip =
		'inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-xs transition-colors bg-surface-3 text-muted hover:text-text';
	const fieldLabel = 'mb-1 block text-xs font-medium text-muted';
	const fieldHint = 'mt-1 text-[11px] text-faint';
</script>

{#snippet countInput(cls = '')}
	<NumberInput
		value={block.content.count || 3}
		min={1}
		max={10}
		class={cls}
		onchange={(v) => set('count', v ?? 3)}
	/>
{/snippet}

<!-- A suggestion from the reference movie, one click to apply. -->
{#snippet seed(label: string, onclick: () => void)}
	<button type="button" class={chip} title="From {refMovie?.title ?? 'reference'}" {onclick}>
		<Plus size={10} />{label}
	</button>
{/snippet}

{#snippet tagSelect(cls = '')}
	<ConfigSelect
		value={block.content.trailer_tag_id}
		class={cls}
		options={idOptions(ctx.trailerTags)}
		placeholder="Any"
		onnumber={(v) => set('trailer_tag_id', v)}
	/>
{/snippet}

{#if ctx.mode === 'template'}
	<!-- A template rule has no concrete criteria — it matches each feature at build
	     time — so it carries the match toggles + tolerance, no footer. -->
	<div class="max-w-3xl space-y-3.5">
		<div class="flex flex-wrap items-start gap-x-5 gap-y-3">
			<div>
				<span class={fieldLabel}>For feature</span>
				<ConfigSelect
					value={block.content.bound_to_feature}
					class="!w-32"
					options={featureOptions(ctx.featureCount)}
					placeholder="Select…"
					onnumber={(v) => set('bound_to_feature', v)}
				/>
			</div>

			<div>
				<span class={fieldLabel}>Trailers</span>
				{@render countInput('!w-20')}
			</div>

			<div>
				<span class={fieldLabel}>Year tolerance ±</span>
				<NumberInput
					value={block.content.year_delta || 5}
					min={1}
					max={20}
					class="!w-20"
					onchange={(v) => set('year_delta', v ?? 5)}
				/>
			</div>

			<div>
				<span class={fieldLabel}>Tag</span>
				{@render tagSelect('!w-36')}
			</div>
		</div>

		<div>
			<span class={fieldLabel}>Match the feature on</span>
			<div class="flex flex-wrap items-center gap-x-4 gap-y-1">
				{#each MATCH_ON as m (m.key)}
					<label class="inline-flex items-center gap-1.5 text-sm text-text">
						<input
							type="checkbox"
							class="accent-accent"
							checked={block.content[m.key] ?? m.fallback}
							onchange={(e) => set(m.key, e.currentTarget.checked)}
						/>
						{m.label}
					</label>
				{/each}
			</div>
			<p class={fieldHint}>
				Trailers share the chosen feature's attributes — year within ± the tolerance.
			</p>
		</div>
	</div>
{:else if isBoundToRandom}
	<ConfigForm>
		<ConfigField label="Reference movie" wide>
			<span class="inline-flex items-center gap-1.5 text-sm text-muted">
				<Dices size={13} /> Random movie (block {block.content.bound_to_block_order})
			</span>
		</ConfigField>
		<ConfigField label="Tag">
			{@render tagSelect()}
		</ConfigField>
		<ConfigField label="Number of trailers">
			{@render countInput()}
		</ConfigField>
	</ConfigForm>
{:else}
	<div class="max-w-3xl space-y-3.5">
		<!-- Seed line: the reference is a modifier over everything, not a column. -->
		<div class="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
			{#if refMovie}
				<span class="text-xs font-medium text-muted">Seed</span>
				<span class="inline-flex items-center gap-1.5">
					<Film size={13} class="text-muted" />{refMovie.title}
				</span>
				<span class="text-faint">·</span>
				<button
					type="button"
					class="text-xs text-accent hover:underline"
					onclick={() => void pickReference()}>Change</button
				>
				<button
					type="button"
					class="text-xs text-muted hover:text-danger"
					onclick={() => set('reference_movie_id', null)}>Clear</button
				>
				<span class="text-xs text-faint"
					>— seeds the criteria and ranks the picks, not a filter</span
				>
			{:else}
				<button
					type="button"
					class="inline-flex items-center gap-1.5 rounded-sm border border-border-strong bg-surface-2 px-2.5 py-1 text-sm hover:bg-surface-3"
					onclick={() => void pickReference()}
				>
					<Film size={13} /> Seed from a movie…
				</button>
				<span class="text-xs text-faint">optional — seeds the criteria and ranks the picks</span>
			{/if}
		</div>

		<div class="flex flex-wrap items-start gap-x-5 gap-y-3">
			<div class="min-w-[15rem] grow">
				<span class={fieldLabel}>Genres</span>
				<GenreChips
					selected={selectedGenreIds}
					genres={ctx.genres}
					onchange={(ids) => set('genre_ids', ids)}
				>
					{#each seedGenres as id (id)}
						{@render seed(genreName(id), () => set('genre_ids', [...selectedGenreIds, id]))}
					{/each}
				</GenreChips>
				<p class={fieldHint}>A trailer needs at least one; more shared rank first.</p>
			</div>

			<div>
				<span class={fieldLabel}>Certificate ≤</span>
				<div class="flex items-center gap-1.5">
					<ConfigSelect
						value={block.content.certificate_ceiling || ''}
						class="!w-24"
						options={ctx.certifications.map((c) => ({ value: c, label: c }))}
						placeholder="No limit"
						onchange={(v) => set('certificate_ceiling', v)}
					/>
					{#if refCert && refCert !== block.content.certificate_ceiling}
						{@render seed(refCert, () => set('certificate_ceiling', refCert))}
					{/if}
				</div>
			</div>

			<div>
				<span class={fieldLabel}>Trailers</span>
				{@render countInput('!w-20')}
			</div>

			<div>
				<span class={fieldLabel}>Year range</span>
				<div class="flex flex-wrap items-center gap-x-1.5 gap-y-1">
					<NumberInput
						value={block.content.year_from ?? null}
						min={1900}
						max={2100}
						placeholder="From"
						class="!w-[4.5rem]"
						onchange={(v) => set('year_from', v)}
					/>
					<span class="text-faint">–</span>
					<NumberInput
						value={block.content.year_to ?? null}
						min={1900}
						max={2100}
						placeholder="To"
						class="!w-[4.5rem]"
						onchange={(v) => set('year_to', v)}
					/>
					{#if refYear}
						{@render seed(`${refYear - SEED_YEARS}-${refYear + SEED_YEARS}`, seedFromReferenceYear)}
					{/if}
				</div>
			</div>

			<div>
				<span class={fieldLabel}>Tag</span>
				{@render tagSelect('!w-36')}
			</div>
		</div>

		{#if match}
			<div class="border-t border-border pt-2.5">
				<StatusLamp colour={match.colour} pending={match.pending}>{match.text}</StatusLamp>
			</div>
		{/if}
	</div>
{/if}
