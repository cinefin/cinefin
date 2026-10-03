<script lang="ts">
	// Manual mode: find a film, trailer or media item (or paste a URL) and play it now or queue it.
	import { ListPlus, Play, Search } from '@lucide/svelte';
	import { api, unwrap, ApiError } from '$lib/api/client';
	import { mutate } from '$lib/api/mutate';
	import { unwrapLoose } from '$lib/jobs';
	import { showToast } from '$lib/toast.svelte';
	import TypeBadge from '$lib/components/TypeBadge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Input from '$lib/components/ui/Input.svelte';

	type Kind = 'movie' | 'trailer' | 'media' | 'url';
	interface Hit {
		kind: Kind;
		id: number;
		title: string;
		year?: number | null;
	}

	interface Props {
		/** Asks before ending a loaded programme; resolves true to go ahead. */
		confirmEnd: (programme: string) => Promise<boolean>;
		onchanged: () => void;
	}
	let { confirmEnd, onchanged }: Props = $props();

	const BADGE: Record<Kind, string> = {
		movie: 'movie',
		trailer: 'trailer',
		media: 'bumper',
		url: 'system'
	};

	let q = $state('');
	let url = $state('');
	let hits = $state<Hit[]>([]);
	let searching = $state(false);

	$effect(() => {
		const term = q.trim();
		if (term.length < 2) {
			hits = [];
			return;
		}
		const t = setTimeout(() => void search(term), 250);
		return () => clearTimeout(t);
	});

	async function search(term: string) {
		searching = true;
		const [films, trailers, media] = await Promise.all([
			unwrap(api.GET('/api/v2/movies/list', { params: { query: { search: term, per_page: 6 } } }))
				.then((d) => d?.items ?? [])
				.catch(() => []),
			unwrapLoose<{ trailers: { id: number; title: string; year: number }[] }>(
				api.GET('/api/v2/trailers/library', { params: { query: { q: term, limit: 6 } } })
			)
				.then((d) => d.trailers)
				.catch(() => []),
			unwrapLoose<{ media: { id: number; title: string }[] }>(
				api.GET('/api/v2/media/list', { params: { query: { search: term, per_page: 6 } } })
			)
				.then((d) => d.media)
				.catch(() => [])
		]);
		if (term !== q.trim()) return;
		const as =
			(kind: Kind) =>
			({ id, title, year }: Omit<Hit, 'kind'>): Hit => ({ kind, id, title, year });
		hits = [...films.map(as('movie')), ...trailers.map(as('trailer')), ...media.map(as('media'))];
		searching = false;
	}

	async function add(body: { kind: Kind; id?: number; url?: string }, now: boolean) {
		const post = (end_programme: boolean) =>
			mutate(api.POST('/api/v2/playout/manual', { body: { ...body, now, end_programme } }));
		try {
			try {
				await post(false);
			} catch (e) {
				if (!(e instanceof ApiError && e.errorCode === 'PROGRAMME_LOADED')) throw e;
				if (!(await confirmEnd(e.message))) return;
				await post(true);
			}
			if (body.kind === 'url') url = '';
			onchanged();
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'The player did not take it', 'error');
		}
	}
</script>

<section class="border border-border bg-surface-1 p-4">
	<label class="flex items-center gap-2">
		<Search size={15} class="shrink-0 text-faint" />
		<span class="sr-only">Search films, trailers and media</span>
		<Input
			type="search"
			bind:value={q}
			placeholder="Search films, trailers, media…"
			class="flex-1"
		/>
	</label>

	{#if hits.length}
		<ul class="mt-3 divide-y divide-border border-y border-border">
			{#each hits as hit (`${hit.kind}-${hit.id}`)}
				<li class="flex items-center gap-3 py-1.5">
					<TypeBadge type={BADGE[hit.kind]} short col class="!text-[0.6rem]" />
					<span class="min-w-0 flex-1 truncate text-sm">
						{hit.title}{#if hit.year}<span class="text-faint"> ({hit.year})</span>{/if}
					</span>
					<Button size="sm" variant="primary" onclick={() => void add(hit, true)}>
						<Play size={12} /> Play
					</Button>
					<Button size="sm" onclick={() => void add(hit, false)}>
						<ListPlus size={12} /> Queue
					</Button>
				</li>
			{/each}
		</ul>
	{:else if q.trim().length >= 2 && !searching}
		<p class="mt-3 text-sm text-muted">Nothing matches "{q.trim()}".</p>
	{/if}

	<form
		class="mt-4 flex flex-wrap items-center gap-2 border-t border-border pt-4"
		onsubmit={(e) => {
			e.preventDefault();
			void add({ kind: 'url', url }, true);
		}}
	>
		<label for="manual-url" class="text-sm text-muted">Or a URL</label>
		<Input id="manual-url" bind:value={url} placeholder="https://…" class="min-w-0 flex-1" />
		<Button size="sm" variant="primary" type="submit" disabled={!url.trim()}>
			<Play size={12} /> Play
		</Button>
		<Button size="sm" disabled={!url.trim()} onclick={() => void add({ kind: 'url', url }, false)}>
			<ListPlus size={12} /> Queue
		</Button>
	</form>
</section>
