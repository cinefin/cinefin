<script lang="ts">
	import { Dices, Film, Plus, X } from '@lucide/svelte';
	import { api, unwrap } from '$lib/api/client';
	import StatusLamp from '$lib/components/StatusLamp.svelte';
	import ConfigField from '../ConfigField.svelte';
	import ConfigForm from '../ConfigForm.svelte';
	import ConfigSelect from '../ConfigSelect.svelte';
	import NumberInput from '../NumberInput.svelte';
	import type { EditorBlock, EditorContext } from '../types';

	interface Props {
		block: EditorBlock;
		ctx: EditorContext;
		commit: (mutate: () => void) => void;
	}

	let { block, ctx, commit }: Props = $props();

	const isBoundToRandom = $derived(
		ctx.mode === 'programme' && block.content.bound_to_block_order != null
	);
	const featureOptions = $derived(
		Array.from({ length: ctx.featureCount }, (_, i) => ({
			value: String(i + 1),
			label: `Feature ${i + 1}`
		}))
	);
	const tagOptions = $derived(ctx.trailerTags.map((t) => ({ value: String(t.id), label: t.name })));
	const certOptions = $derived(ctx.certifications.map((c) => ({ value: c, label: c })));

	function set<K extends keyof EditorBlock['content']>(
		field: K,
		value: EditorBlock['content'][K]
	): void {
		commit(() => {
			block.content[field] = value;
		});
	}

	const refMovie = $derived(
		block.content.reference_movie_id
			? ctx.movies.find((m) => m.id === block.content.reference_movie_id)
			: null
	);

	async function pickReference() {
		const picked = await ctx.pickMovie?.();
		if (!picked) return;
		try {
			const m = await unwrap(
				api.GET('/api/v2/movies/{movie_id}', { params: { path: { movie_id: picked.id } } })
			);
			commit(() => {
				block.content.reference_movie_id = picked.id;
				block.content.genre_ids = m.genres ?? [];
				block.content.certificate_ceiling = m.certification ?? '';
				block.content.year_from = m.year ? m.year - seedYearWindow : null;
				block.content.year_to = m.year ? m.year + seedYearWindow : null;
			});
			// Seed the chips from the detail just fetched so the $effect below
			// doesn't issue a second identical GET for the same film.
			refGenreIds = m.genres ?? [];
			refCert = m.certification ?? '';
			refYear = m.year ?? null;
			lastSeededId = picked.id;
		} catch {
			set('reference_movie_id', picked.id);
		}
	}

	let refGenreIds = $state<number[]>([]);
	let refCert = $state('');
	let refYear = $state<number | null>(null);
	let lastSeededId = $state<number | null>(null);
	$effect(() => {
		const id = block.content.reference_movie_id;
		if (ctx.mode !== 'programme' || !id) {
			refGenreIds = [];
			refCert = '';
			refYear = null;
			lastSeededId = null;
			return;
		}
		if (id === lastSeededId) return; // chips already seeded for this film
		let cancelled = false;
		unwrap(api.GET('/api/v2/movies/{movie_id}', { params: { path: { movie_id: id } } }))
			.then((m) => {
				if (cancelled) return;
				refGenreIds = m.genres ?? [];
				refCert = m.certification ?? '';
				refYear = m.year ?? null;
				lastSeededId = id;
			})
			.catch(() => {});
		return () => {
			cancelled = true;
		};
	});

	const selectedGenreIds = $derived(block.content.genre_ids ?? []);
	function addGenre(id: number) {
		if (!selectedGenreIds.includes(id)) set('genre_ids', [...selectedGenreIds, id]);
	}
	function removeGenre(id: number) {
		set(
			'genre_ids',
			selectedGenreIds.filter((x) => x !== id)
		);
	}
	const genreName = (id: number) => ctx.genres.find((g) => g.id === id)?.name ?? String(id);
	const seedGenres = $derived(refGenreIds.filter((id) => !selectedGenreIds.includes(id)));
	const addableGenres = $derived(ctx.genres.filter((g) => !selectedGenreIds.includes(g.id)));

	const seedYearWindow = 5;
	function seedFromReferenceYear() {
		if (refYear == null) return;
		commit(() => {
			block.content.year_from = refYear! - seedYearWindow;
			block.content.year_to = refYear! + seedYearWindow;
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
		const query: Record<string, string | number> = { count: block.content.count || 3 };
		if (block.content.reference_movie_id) query.movie_id = block.content.reference_movie_id;
		if (selectedGenreIds.length) query.genre_ids = selectedGenreIds.join(',');
		if (block.content.certificate_ceiling)
			query.certificate_ceiling = block.content.certificate_ceiling;
		if (block.content.year_from != null) query.year_from = block.content.year_from;
		if (block.content.year_to != null) query.year_to = block.content.year_to;
		if (block.content.trailer_tag_id) query.tag_id = block.content.trailer_tag_id;
		const count = block.content.count || 3;

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

	const checkCls = 'inline-flex items-center gap-1.5 text-sm text-text';
	const chip = 'inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-xs transition-colors';
	const fieldLabel = 'mb-1 block text-xs font-medium text-muted';
	const fieldHint = 'mt-1 text-[11px] text-faint';
</script>

{#if ctx.mode === 'template'}
	<!-- Sibling of the programme-mode bar below: same labelled-field rhythm. A
	     template rule has no concrete criteria — it matches each feature at
	     build time — so it carries the match toggles + tolerance, no footer. -->
	<div class="max-w-3xl space-y-3.5">
		<div class="flex flex-wrap items-start gap-x-5 gap-y-3">
			<div>
				<span class={fieldLabel}>For feature</span>
				<ConfigSelect
					value={block.content.bound_to_feature ? String(block.content.bound_to_feature) : ''}
					class="!w-32"
					options={featureOptions}
					placeholder="Select…"
					onchange={(v) => set('bound_to_feature', v === '' ? null : parseInt(v, 10))}
				/>
			</div>

			<div>
				<span class={fieldLabel}>Trailers</span>
				<NumberInput
					value={block.content.count || 3}
					min={1}
					max={10}
					class="!w-20"
					onchange={(v) => set('count', v ?? 3)}
				/>
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
				<ConfigSelect
					value={block.content.trailer_tag_id ? String(block.content.trailer_tag_id) : ''}
					class="!w-36"
					options={tagOptions}
					placeholder="Any"
					onchange={(v) => set('trailer_tag_id', v === '' ? null : parseInt(v, 10))}
				/>
			</div>
		</div>

		<div>
			<span class={fieldLabel}>Match the feature on</span>
			<div class="flex flex-wrap items-center gap-x-4 gap-y-1">
				<label class={checkCls}>
					<input
						type="checkbox"
						class="accent-accent"
						checked={block.content.match_genres !== false}
						onchange={(e) => set('match_genres', (e.target as HTMLInputElement).checked)}
					/> Genre
				</label>
				<label class={checkCls}>
					<input
						type="checkbox"
						class="accent-accent"
						checked={block.content.match_certification !== false}
						onchange={(e) => set('match_certification', (e.target as HTMLInputElement).checked)}
					/> Rating
				</label>
				<label class={checkCls}>
					<input
						type="checkbox"
						class="accent-accent"
						checked={block.content.match_year === true}
						onchange={(e) => set('match_year', (e.target as HTMLInputElement).checked)}
					/> Year
				</label>
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
			<ConfigSelect
				value={block.content.trailer_tag_id ? String(block.content.trailer_tag_id) : ''}
				options={tagOptions}
				placeholder="Any"
				onchange={(v) => set('trailer_tag_id', v === '' ? null : parseInt(v, 10))}
			/>
		</ConfigField>
		<ConfigField label="Number of trailers">
			<NumberInput
				value={block.content.count || 3}
				min={1}
				max={10}
				onchange={(v) => set('count', v ?? 3)}
			/>
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
				<span class="text-xs text-faint">— seeds the criteria and ranks the picks, not a filter</span
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

		<!-- Criteria as one wrapping bar of labelled fields. -->
		<div class="flex flex-wrap items-start gap-x-5 gap-y-3">
			<div class="min-w-[15rem] grow">
				<span class={fieldLabel}>Genres</span>
				<div class="flex flex-wrap items-center gap-1.5">
					{#if !selectedGenreIds.length}
						<span class="text-xs text-faint">Any genre</span>
					{:else}
						{#each selectedGenreIds as id (id)}
							<span class="{chip} bg-accent/15 text-accent">
								{genreName(id)}
								<button type="button" aria-label="Remove genre" onclick={() => removeGenre(id)}>
									<X size={11} />
								</button>
							</span>
						{/each}
					{/if}
					{#if addableGenres.length}
						<ConfigSelect
							value=""
							class="!h-7 !w-auto !pr-6 text-xs"
							options={addableGenres.map((g) => ({ value: String(g.id), label: g.name }))}
							placeholder="+ add"
							onchange={(v) => v && addGenre(parseInt(v, 10))}
						/>
					{/if}
					{#each seedGenres as id (id)}
						<button
							type="button"
							class="{chip} bg-surface-3 text-muted hover:text-text"
							title="From {refMovie?.title ?? 'reference'}"
							onclick={() => addGenre(id)}
						>
							<Plus size={10} />{genreName(id)}
						</button>
					{/each}
				</div>
				<p class={fieldHint}>A trailer needs at least one; more shared rank first.</p>
			</div>

			<div>
				<span class={fieldLabel}>Certificate ≤</span>
				<div class="flex items-center gap-1.5">
					<ConfigSelect
						value={block.content.certificate_ceiling || ''}
						class="!w-24"
						options={certOptions}
						placeholder="No limit"
						onchange={(v) => set('certificate_ceiling', v)}
					/>
					{#if refCert && refCert !== block.content.certificate_ceiling}
						<button
							type="button"
							class="{chip} bg-surface-3 text-muted hover:text-text"
							title="From {refMovie?.title ?? 'reference'}"
							onclick={() => set('certificate_ceiling', refCert)}
						>
							<Plus size={10} />{refCert}
						</button>
					{/if}
				</div>
			</div>

			<div>
				<span class={fieldLabel}>Trailers</span>
				<NumberInput
					value={block.content.count || 3}
					min={1}
					max={10}
					class="!w-20"
					onchange={(v) => set('count', v ?? 3)}
				/>
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
						<button
							type="button"
							class="{chip} bg-surface-3 text-muted hover:text-text"
							title="From {refMovie?.title ?? 'reference'}"
							onclick={seedFromReferenceYear}
						>
							<Plus size={10} />{refYear - seedYearWindow}-{refYear + seedYearWindow}
						</button>
					{/if}
				</div>
			</div>

			<div>
				<span class={fieldLabel}>Tag</span>
				<ConfigSelect
					value={block.content.trailer_tag_id ? String(block.content.trailer_tag_id) : ''}
					class="!w-36"
					options={tagOptions}
					placeholder="Any"
					onchange={(v) => set('trailer_tag_id', v === '' ? null : parseInt(v, 10))}
				/>
			</div>
		</div>

		<!-- The payoff: promoted from a faint centred line to a status lamp. -->
		{#if match}
			<div class="border-t border-border pt-2.5">
				<StatusLamp colour={match.colour} pending={match.pending}>{match.text}</StatusLamp>
			</div>
		{/if}
	</div>
{/if}
