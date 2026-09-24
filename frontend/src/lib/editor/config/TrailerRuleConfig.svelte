<script lang="ts">
	import { Dices, Film, Plus, X } from '@lucide/svelte';
	import { api, unwrap } from '$lib/api/client';
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

	let matchText = $state<string | null>(null);
	let matchSeq = 0;
	$effect(() => {
		if (ctx.mode !== 'programme' || isBoundToRandom) {
			matchText = null;
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
		matchText = 'Checking…';
		const timer = setTimeout(async () => {
			try {
				const data = await unwrap(api.GET('/api/v2/trailers/match-test', { params: { query } }));
				if (seq !== matchSeq) return;
				const n = data.matched;
				if (n === 0) matchText = 'No trailers match - nothing will play here';
				else if (n >= count) matchText = `${n} trailer${n === 1 ? '' : 's'} match`;
				else matchText = `Only ${n} of ${count} match - the rest of the slot stays empty`;
			} catch {
				if (seq === matchSeq) matchText = null;
			}
		}, 300);
		return () => clearTimeout(timer);
	});

	const checkCls = 'inline-flex items-center gap-1.5 text-sm text-text';
	const chip = 'inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-xs transition-colors';
	const colHead = 'mb-2 block text-xs font-medium text-muted';
	const fieldLabel = 'mb-1 block text-xs font-medium text-muted';
	const fieldHint = 'mt-1 text-xs text-faint';
</script>

{#if ctx.mode === 'template'}
	<ConfigForm>
		<ConfigField label="For feature">
			<ConfigSelect
				value={block.content.bound_to_feature ? String(block.content.bound_to_feature) : ''}
				options={featureOptions}
				placeholder="Select..."
				onchange={(v) => set('bound_to_feature', v === '' ? null : parseInt(v, 10))}
			/>
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
		<ConfigField label="Year tolerance (±)">
			<NumberInput
				value={block.content.year_delta || 5}
				min={1}
				max={20}
				onchange={(v) => set('year_delta', v ?? 5)}
			/>
		</ConfigField>
		<ConfigField label="Match on" wide>
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
		</ConfigField>
	</ConfigForm>
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
	<div class="max-w-2xl">
		<div class="grid gap-x-6 gap-y-6 sm:grid-cols-2">
			<section class="min-w-0 space-y-4">
				<h4 class={colHead}>Reference (optional)</h4>

				<div class="min-w-0">
					<div class="flex flex-wrap items-center gap-2">
						{#if refMovie}
							<span class="inline-flex items-center gap-1.5 text-sm">
								<Film size={13} class="text-muted" />{refMovie.title}
							</span>
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
						{:else}
							<button
								type="button"
								class="inline-flex items-center gap-1.5 rounded-sm border border-border-strong bg-surface-2 px-2.5 py-1 text-sm hover:bg-surface-3"
								onclick={() => void pickReference()}
							>
								<Film size={13} /> Choose movie…
							</button>
						{/if}
					</div>
					<p class={fieldHint}>Seeds the criteria and ranks the picks; not a filter.</p>
				</div>

				<div class="min-w-0">
					<span class={fieldLabel}>Number of trailers</span>
					<NumberInput
						value={block.content.count || 3}
						min={1}
						max={10}
						class="!w-20"
						onchange={(v) => set('count', v ?? 3)}
					/>
				</div>
			</section>

			<section class="min-w-0 space-y-4">
				<h4 class={colHead}>Criteria</h4>

				<div class="min-w-0">
					<span class={fieldLabel}>Genres</span>
					<div class="min-w-0 space-y-1.5">
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
						</div>
						{#if seedGenres.length}
							<div class="flex flex-wrap items-center gap-1.5">
								<span class="text-xs text-faint">From {refMovie?.title ?? 'reference'}:</span>
								{#each seedGenres as id (id)}
									<button
										type="button"
										class="{chip} bg-surface-3 text-muted hover:text-text"
										onclick={() => addGenre(id)}
									>
										<Plus size={10} />{genreName(id)}
									</button>
								{/each}
							</div>
						{/if}
					</div>
					<p class={fieldHint}>
						Best effort - a trailer must share at least one; those matching more rank first.
					</p>
				</div>

				<div class="min-w-0">
					<span class={fieldLabel}>Certificate ceiling</span>
					<div class="flex min-w-0 flex-wrap items-center gap-2">
						<ConfigSelect
							value={block.content.certificate_ceiling || ''}
							class="!w-28"
							options={certOptions}
							placeholder="No limit"
							onchange={(v) => set('certificate_ceiling', v)}
						/>
						{#if refCert && refCert !== block.content.certificate_ceiling}
							<button
								type="button"
								class="{chip} bg-surface-3 text-muted hover:text-text"
								onclick={() => set('certificate_ceiling', refCert)}
							>
								<Plus size={10} />{refCert}
							</button>
						{/if}
					</div>
					<p class={fieldHint}>Never above this rating.</p>
				</div>

				<div class="min-w-0">
					<span class={fieldLabel}>Year range</span>
					<div class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1.5">
						<NumberInput
							value={block.content.year_from ?? null}
							min={1900}
							max={2100}
							placeholder="From"
							class="!w-[4.5rem]"
							onchange={(v) => set('year_from', v)}
						/>
						<span class="text-faint">-</span>
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
								onclick={seedFromReferenceYear}
							>
								<Plus size={10} />{refYear - seedYearWindow}-{refYear + seedYearWindow}
							</button>
						{/if}
					</div>
				</div>

				<div class="min-w-0">
					<span class={fieldLabel}>Tag</span>
					<ConfigSelect
						value={block.content.trailer_tag_id ? String(block.content.trailer_tag_id) : ''}
						options={tagOptions}
						placeholder="Any"
						onchange={(v) => set('trailer_tag_id', v === '' ? null : parseInt(v, 10))}
					/>
				</div>
			</section>
		</div>

		{#if matchText}
			<p class="mt-6 text-center text-xs text-faint">{matchText}</p>
		{/if}
	</div>
{/if}
