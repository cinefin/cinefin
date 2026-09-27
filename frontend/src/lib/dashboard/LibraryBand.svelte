<script lang="ts">
	import { base } from '$app/paths';
	import { api } from '$lib/api/client';
	import { unwrapLoose } from '$lib/jobs';
	import { relativeTime } from '$lib/format';
	import { health } from '$lib/stores/health.svelte';
	import { showToast } from '$lib/toast.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import StatusLamp from '$lib/components/StatusLamp.svelte';
	import PosterShelf from './PosterShelf.svelte';
	import type { DashboardData } from './data.svelte';

	let { data }: { data: DashboardData } = $props();

	const source = $derived(data.source);
	const job = $derived(data.activeSync);
	$effect(() => health.subscribe());
	const disk = $derived(health.check('disk_media'));
	// The check reports "19.2 GB free of 168.5 GB (11%)"; split it for the figure.
	const diskFree = $derived(disk?.detail.match(/^(.+?) free of (.+?) \(/));
	const TONE = { warn: 'text-warning', error: 'text-danger' } as const;

	const figures = $derived([
		{
			label: 'Films',
			value: data.stats.data?.total_movies ?? '-',
			note: data.stats.data?.total_runtime_readable,
			href: `${base}/library`
		},
		{
			label: 'Trailers',
			value: data.trailers.data?.total_trailers ?? '-',
			note: data.trailers.data?.api_key_configured === false ? 'no TMDB key' : undefined,
			href: `${base}/trailers`
		},
		{ label: 'Programmes', value: data.programmes.data?.total ?? '-', href: `${base}/programmes` },
		{
			label: 'Library size',
			value: data.stats.data?.total_size_bytes ? data.stats.data.total_size_readable : '—',
			note: 'on the media server'
		},
		{
			label: 'Free space',
			value: diskFree?.[1] ?? disk?.detail ?? '-',
			note: diskFree ? `of ${diskFree[2]}` : undefined,
			tone: TONE[disk?.status as keyof typeof TONE]
		}
	]);

	async function syncNow() {
		if (!source) return;
		try {
			await unwrapLoose(
				api.POST('/api/v2/sync/sources/{source_id}/runs', {
					params: { path: { source_id: source.id } },
					body: { operation: 'sync', params: {}, max_attempts: 1 }
				})
			);
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Could not start the sync', 'error');
		}
	}
</script>

<div class="mt-6 flex flex-wrap items-center gap-3 border-t border-border pt-4">
	<h2 class="font-display text-xl">Library</h2>
	<div class="ml-auto flex items-center gap-3">
		{#if job}
			<StatusLamp colour="blue" pending quiet>
				{#if job.state === 'queued'}
					Sync queued…
				{:else}
					Syncing · {job.current ?? 0}
					{(job.current ?? 0) === 1 ? 'film' : 'films'} so far{job.percentage
						? ` · ${Math.round(job.percentage)}%`
						: ''}
				{/if}
			</StatusLamp>
		{:else if source}
			<StatusLamp colour="neutral" quiet>
				{data.lastSync ? `Synced ${relativeTime(data.lastSync)}` : 'Never synced'} · {source.name}
			</StatusLamp>
		{/if}
		{#if source?.enabled}
			<Button size="sm" onclick={() => void syncNow()} disabled={!!job}>Sync now</Button>
		{:else if data.sources.data}
			<Button size="sm" href="{base}/settings?tab=library">
				{source ? 'Library source settings' : 'Add a library source'}
			</Button>
		{/if}
	</div>
</div>

<div class="mt-3 grid grid-cols-1 gap-3 @4xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
	<Card title="Collection">
		<ul class="-mx-4 -my-1 divide-y divide-border">
			{#each figures as f (f.label)}
				<li>
					<svelte:element
						this={f.href ? 'a' : 'div'}
						href={f.href}
						class="flex items-baseline gap-3 px-4 py-1 {f.href ? 'hover:bg-surface-2' : ''}"
					>
						<span class="w-24 shrink-0 text-sm text-muted">{f.label}</span>
						<span class="font-mono text-sm {f.tone ?? ''}">{f.value}</span>
						{#if f.note}
							<span class="ml-auto truncate font-mono text-xs text-faint">{f.note}</span>
						{/if}
					</svelte:element>
				</li>
			{/each}
		</ul>
	</Card>

	<Card title="Recently added">
		{#snippet actions()}
			<a class="text-xs text-muted hover:text-text" href="{base}/library">Library</a>
		{/snippet}
		{#if data.recentMovies.loading}
			<Spinner size="sm" />
		{:else if data.recentMovies.error}
			<ErrorState
				error={data.recentMovies.error}
				retry={() => void data.recentMovies.load()}
				compact
			/>
		{:else if !data.movies.length}
			<p class="text-sm text-muted">
				No films yet.
				<a class="text-accent hover:underline" href="{base}/settings?tab=library"
					>Add a library source</a
				>.
			</p>
		{:else}
			<PosterShelf movies={data.movies} onmutated={() => data.refreshLibrary()} />
		{/if}
	</Card>
</div>
