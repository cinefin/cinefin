<script lang="ts">
	// The home screen — a status board for the whole system (data in lib/dashboard/data.svelte.ts).
	import { base } from '$app/paths';
	import {
		CalendarClock,
		Clapperboard,
		Clock,
		Film,
		HardDrive,
		ListVideo,
		MonitorPlay,
		Settings
	} from '@lucide/svelte';
	import { playout } from '$lib/stores/playout.svelte';
	import { playoutReach } from '$lib/stores/playoutReach.svelte';
	import { dayLabel, formatClock, formatRuntime, formatTime, relativeTime } from '$lib/format';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Banner from '$lib/components/ui/Banner.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import StatusLamp from '$lib/components/StatusLamp.svelte';
	import Tally from '$lib/components/Tally.svelte';
	import TypeBadge from '$lib/components/TypeBadge.svelte';
	import ArtBackdrop from '$lib/dashboard/ArtBackdrop.svelte';
	import GettingStarted, { type Step } from '$lib/dashboard/GettingStarted.svelte';
	import PosterShelf from '$lib/dashboard/PosterShelf.svelte';
	import StatTile from '$lib/dashboard/StatTile.svelte';
	import {
		DashboardData,
		SCHEDULE_BADGE,
		isToday,
		itemProgress,
		playoutBadge,
		untilLabel
	} from '$lib/dashboard/data.svelte';

	const data = new DashboardData();
	$effect(() => data.start());

	$effect(() => playout.subscribe());
	$effect(() => playoutReach.subscribe());

	const prog = $derived(playout.status?.programme ?? null);
	const badge = $derived(playoutBadge(prog?.state));
	const pb = $derived(playout.status?.playback ?? null);
	const progressPct = $derived(itemProgress(pb));
	const next = $derived(data.nextScreening);
	const nextStart = $derived(next ? new Date(next.start_time) : null);

	// Tied to the programme, not the item, so the hero doesn't change picture at every trailer.
	const heroArt = $derived.by(() => {
		if (!prog) return null;
		const meta = playout.status?.current_item?.details?.metadata as
			| { thumbnail_url?: string }
			| undefined;
		return data.posterForProgramme(prog.id) ?? meta?.thumbnail_url ?? null;
	});

	const endsAt = $derived.by(() => {
		const remaining = playout.status?.playlist?.programme_remaining_time;
		return remaining ? new Date(Date.now() + remaining * 1000) : null;
	});

	const diskTone = $derived(
		data.disk?.status === 'error' ? 'danger' : data.disk?.status === 'warn' ? 'warning' : 'neutral'
	);

	const HEALTH_BADGE: Record<string, 'success' | 'warning' | 'danger' | 'default'> = {
		ok: 'success',
		warn: 'warning',
		error: 'danger',
		unknown: 'default'
	};
	const HEALTH_WORD: Record<string, string> = {
		ok: 'OK',
		warn: 'Needs attention',
		error: 'Needs fixing',
		unknown: 'Checking…'
	};

	// Only the onboarding "no host yet" state lives here; "host unreachable" is the
	// app-wide banner in +layout.svelte. Null while the first probe is in flight / healthy.
	const reachNotice = $derived.by(() => {
		if (!playoutReach.checked || playoutReach.state !== 'unconfigured') return null;
		return playoutReach.hostCount > 0
			? {
					title: 'No playout host is active.',
					body: 'Point a host at your theater machine and make it active to enable playback.',
					cta: 'Set up playout'
				}
			: {
					title: 'No playout host configured.',
					body: 'Add a playout host to enable playback.',
					cta: 'Add a playout host'
				};
	});

	// Every step is read from real state, not a "visited" flag.
	let gettingStartedUp = $state(false);

	const firstRunReady = $derived(
		playoutReach.checked &&
			!data.stats.loading &&
			!data.trailers.loading &&
			!data.programmes.loading
	);

	const gettingStartedSteps = $derived.by((): Step[] => {
		const movies = data.stats.data?.total_movies ?? 0;
		const trailers = data.trailers.data?.total_trailers ?? 0;
		const programmes = data.programmes.data?.programmes ?? [];
		const played = programmes.some((p) => p.last_played_at);
		return [
			{
				label: 'Connect the player',
				done: playoutReach.state === 'ok',
				note: 'Connected',
				href: `${base}/settings?tab=playout`,
				action: 'Set up'
			},
			{
				label: 'Sync a movie library',
				done: movies > 0,
				note: `${movies.toLocaleString()} movies`,
				href: `${base}/library?sync=open`,
				action: 'Sync'
			},
			{
				label: 'Fetch some trailers',
				done: trailers > 0,
				note: `${trailers.toLocaleString()} trailers`,
				href: `${base}/trailers?fetch=open`,
				action: 'Fetch'
			},
			{
				label: 'Build your first programme',
				done: programmes.length > 0,
				note: `${programmes.length} built`,
				href: `${base}/programmes/create`,
				action: 'Create'
			},
			{
				label: 'Put it on screen',
				done: played,
				note: 'Played',
				href: `${base}/programmes`,
				action: 'Choose one'
			}
		];
	});
</script>

<svelte:head><title>Dashboard - Cinefin</title></svelte:head>

<GettingStarted steps={gettingStartedSteps} ready={firstRunReady} bind:visible={gettingStartedUp} />

{#if reachNotice && !gettingStartedUp}
	<Banner severity="warning" align="start" title={reachNotice.title} class="mb-3">
		{reachNotice.body}
		{#snippet actions()}
			<a
				href="{base}/settings?tab=playout"
				class="inline-flex items-center gap-1 font-medium text-warning hover:underline"
			>
				<Settings size={13} />
				{reachNotice.cta}
			</a>
		{/snippet}
	</Banner>
{/if}

{#if data.activeSync}
	<div class="mb-3 rounded-md border border-accent-dim bg-accent/10 px-3 py-2 text-sm text-accent">
		<div class="flex items-center gap-2.5">
			<!-- Work in transition: a breathing lamp, not a spinner (spec M4). -->
			<i class="lamp-pending h-2 w-2 flex-none bg-accent" aria-hidden="true"></i>
			{#if data.activeSync.state === 'queued'}
				<span>Library sync queued - waiting to start…</span>
			{:else}
				<span>
					Syncing your library - {data.activeSync.current ?? 0}
					{(data.activeSync.current ?? 0) === 1 ? 'movie' : 'movies'} so far…
				</span>
				{#if data.activeSync.percentage}
					<span class="ml-auto shrink-0 font-mono text-xs">
						{Math.round(data.activeSync.percentage)}%
					</span>
				{/if}
			{/if}
		</div>
		{#if data.activeSync.total && data.activeSync.state !== 'queued'}
			<div
				class="mt-2 h-1.5 overflow-hidden rounded-xs bg-accent/20"
				role="progressbar"
				aria-valuenow={Math.round(data.activeSync.percentage ?? 0)}
				aria-valuemin={0}
				aria-valuemax={100}
			>
				<div
					class="h-full bg-accent transition-[width]"
					style="width: {Math.max(0, Math.min(100, data.activeSync.percentage ?? 0))}%"
				></div>
			</div>
		{/if}
	</div>
{/if}

<!-- `isolate`: keeps this hero's z-10 content from leaking to the root and painting
     over the sticky topbar (also z-10). -->
<section class="relative isolate overflow-hidden border border-border bg-surface-2">
	<ArtBackdrop src={heroArt} from="right" />
	<div class="relative z-10 flex items-stretch gap-5 p-4 sm:p-5">
		{#if heroArt}
			<div
				class="film-grain relative hidden aspect-[2/3] w-20 shrink-0 overflow-hidden border border-border sm:block"
			>
				<img src={heroArt} alt="" class="h-full w-full object-cover" />
			</div>
		{/if}

		<div class="flex min-w-0 flex-1 flex-col justify-center">
			{#if !playout.loaded}
				<Spinner label="Checking playout status…" />
			{:else if playout.error && !playout.status}
				<ErrorState error={playout.error} retry={() => void playout.refresh()} compact />
			{:else if prog}
				<div class="flex items-center gap-3">
					{#if badge.tally}
						<Tally label={badge.label} />
					{:else}
						<StatusLamp colour={badge.colour}>{badge.label}</StatusLamp>
					{/if}
					{#if playout.status?.playlist?.total_items}
						<span class="font-mono text-xs text-faint">
							item {(playout.status.playlist.current_position ?? 0) + 1} of {playout.status.playlist
								.total_items}
						</span>
					{/if}
					<span class="ml-auto shrink-0 text-right font-mono text-2xl leading-none sm:text-3xl">
						{formatTime(pb?.position ?? 0)}
						<span class="text-sm text-faint">/ {formatTime(pb?.duration ?? 0)}</span>
					</span>
				</div>

				<a
					href="{base}/programmes/{prog.id}"
					class="mt-2 block truncate text-2xl font-semibold hover:text-accent"
				>
					{prog.name}
				</a>
				<p class="mt-1 flex min-w-0 items-center gap-2 text-sm text-muted">
					{#if playout.status?.current_item}
						<TypeBadge type={playout.status.current_item.type} short />
					{/if}
					<span class="min-w-0 truncate">
						{playout.status?.current_item?.title || playout.status?.current_item?.name || '-'}
					</span>
					{#if endsAt}
						<span class="ml-auto shrink-0 font-mono text-xs text-faint">
							ends {formatClock(endsAt)}
						</span>
					{/if}
				</p>

				<div
					class="mt-3 h-2 bg-surface-3"
					style="-webkit-mask: repeating-linear-gradient(90deg, #000 0 6px, transparent 6px 9px); mask: repeating-linear-gradient(90deg, #000 0 6px, transparent 6px 9px)"
				>
					<div class="h-full bg-text transition-[width]" style="width: {progressPct}%"></div>
				</div>
			{:else if next && nextStart}
				<div class="flex items-center gap-3 text-sm">
					<StatusLamp colour="neutral" quiet>Idle</StatusLamp>
					<span class="ml-auto font-mono text-xs text-faint">{untilLabel(nextStart)}</span>
				</div>
				<p class="mt-2 flex items-baseline gap-2.5">
					<span class="text-sm text-muted">Next screening</span>
					<span class="font-mono text-2xl leading-none">{formatClock(nextStart)}</span>
					<span class="text-sm text-muted">{dayLabel(nextStart)}</span>
				</p>
				<a
					href="{base}/programmes/{next.programme?.id}"
					class="mt-1.5 block truncate text-2xl font-semibold hover:text-accent"
				>
					{next.programme?.name ?? 'Programme'}
				</a>
				<p class="mt-1 truncate text-sm text-muted">
					{formatRuntime(next.runtime)} · ends {formatClock(
						new Date(nextStart.getTime() + next.runtime * 60000)
					)}
				</p>
			{:else}
				<div class="flex flex-wrap items-center gap-3">
					<MonitorPlay size={18} class="text-faint" />
					<div>
						<p class="text-lg font-semibold">Nothing playing</p>
						<p class="text-sm text-muted">No programme is loaded and nothing is scheduled.</p>
					</div>
					<div class="ml-auto flex gap-2">
						<Button href="{base}/programmes" size="sm">Cue a programme</Button>
						<Button href="{base}/remote" size="sm" variant="primary">Open remote</Button>
					</div>
				</div>
			{/if}
		</div>
	</div>
</section>

<div class="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
	<StatTile
		label="Movies"
		value={data.stats.data?.total_movies ?? '-'}
		note={data.stats.data?.total_runtime_readable}
		icon={Film}
		href="{base}/library"
	/>
	<StatTile
		label="Trailers"
		value={data.trailers.data?.total_trailers ?? '-'}
		note={data.trailers.data?.api_key_configured === false ? 'TMDB key not set' : undefined}
		icon={Clapperboard}
		href="{base}/trailers"
	/>
	<StatTile
		label="Programmes"
		value={data.programmes.data?.total ?? '-'}
		icon={ListVideo}
		href="{base}/programmes"
	/>
	<StatTile
		label="Screenings"
		value={data.upcoming.length}
		note={nextStart ? `next ${formatClock(nextStart)}` : 'none scheduled'}
		icon={CalendarClock}
		href="{base}/schedules"
	/>
	<StatTile
		label="Library size"
		value={data.stats.data?.total_size_readable ?? '-'}
		note={data.disk?.detail}
		tone={diskTone}
		icon={HardDrive}
		href="{base}/system"
	/>
	<StatTile
		label="Last sync"
		value={data.syncing ? 'running' : data.lastSync ? relativeTime(data.lastSync) : 'never'}
		note={data.syncing?.name}
		tone={data.syncing ? 'success' : 'neutral'}
		icon={Clock}
		href="{base}/settings?tab=library"
	/>
</div>

<div class="mt-3 grid gap-3 lg:grid-cols-2">
	<Card title="Next screenings">
		{#snippet actions()}
			<a class="text-xs text-muted hover:text-text" href="{base}/schedules">All</a>
		{/snippet}
		{#if data.schedules.loading}
			<Spinner size="sm" />
		{:else if data.schedules.error}
			<ErrorState error={data.schedules.error} retry={() => void data.schedules.load()} compact />
		{:else if !data.upcoming.length}
			<p class="text-sm text-muted">
				Nothing scheduled.
				<a class="text-accent hover:underline" href="{base}/schedules">Schedule a screening</a>.
			</p>
		{:else}
			<ul class="-mx-4 -my-1 divide-y divide-border">
				{#each data.upcoming.slice(0, 4) as s (s.id)}
					{@const start = new Date(s.start_time)}
					<li class="flex items-center gap-3 px-4 py-1.5">
						<span class="w-12 shrink-0 font-mono text-sm">{formatClock(start)}</span>
						<span class="w-16 shrink-0 text-xs text-faint">{dayLabel(start)}</span>
						<a
							href="{base}/programmes/{s.programme?.id}"
							class="min-w-0 flex-1 truncate text-sm hover:text-accent"
						>
							{s.programme?.name ?? 'Programme'}
						</a>
						{#if s.status !== 'pending' && s.status !== 'scheduled'}
							<Badge variant={SCHEDULE_BADGE[s.status] ?? 'default'}>{s.status}</Badge>
						{:else if isToday(start)}
							<span class="shrink-0 text-xs text-faint">{untilLabel(start)}</span>
						{/if}
						<span class="w-16 shrink-0 text-right font-mono text-xs whitespace-nowrap text-muted">
							{formatRuntime(s.runtime)}
						</span>
					</li>
				{/each}
			</ul>
		{/if}
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
				No movies yet.
				<a class="text-accent hover:underline" href="{base}/settings?tab=library"
					>Add a media source</a
				>.
			</p>
		{:else}
			<PosterShelf
				movies={data.movies.slice(0, 6)}
				cols={6}
				captions={false}
				onmutated={() => data.refreshLibrary()}
			/>
		{/if}
	</Card>

	<Card title="Programmes">
		{#snippet actions()}
			<a class="text-xs text-muted hover:text-text" href="{base}/programmes">All</a>
		{/snippet}
		{#if data.programmes.loading}
			<Spinner size="sm" />
		{:else if data.programmes.error}
			<ErrorState error={data.programmes.error} retry={() => void data.programmes.load()} compact />
		{:else if !data.recentProgrammes.length}
			<p class="text-sm text-muted">
				No programmes yet.
				<a class="text-accent hover:underline" href="{base}/programmes/create">Create one</a>.
			</p>
		{:else}
			<ul class="-mx-4 -my-1 divide-y divide-border">
				{#each data.recentProgrammes.slice(0, 4) as p (p.id)}
					<li class="flex items-center gap-3 px-4 py-1.5">
						<a
							href="{base}/programmes/{p.id}"
							class="min-w-0 flex-1 truncate text-sm hover:text-accent"
						>
							{p.name}
						</a>
						{#if p.playlist_stale}
							<StatusLamp colour="amber">Stale</StatusLamp>
						{/if}
						<span class="shrink-0 text-xs text-faint">
							{p.last_played_at ? relativeTime(p.last_played_at) : 'never played'}
						</span>
						<span class="w-16 shrink-0 text-right font-mono text-xs whitespace-nowrap text-muted">
							{formatRuntime(p.total_runtime)}
						</span>
					</li>
				{/each}
			</ul>
		{/if}
	</Card>

	<Card title="System">
		{#snippet actions()}
			<Badge variant={HEALTH_BADGE[data.overallHealth]}>{HEALTH_WORD[data.overallHealth]}</Badge>
		{/snippet}
		<div class="-mx-4 -my-1 divide-y divide-border">
			<div class="flex items-center justify-between gap-3 px-4 py-1.5">
				<span class="text-sm text-muted">Playout host</span>
				<StatusLamp
					colour={playoutReach.state === 'ok'
						? 'green'
						: playoutReach.state === null
							? 'neutral'
							: playoutReach.state === 'unconfigured'
								? 'amber'
								: 'red'}
					quiet={playoutReach.state === 'ok'}
				>
					{playoutReach.state === 'ok'
						? playoutReach.hostName || 'reachable'
						: playoutReach.state === 'unreachable'
							? 'unreachable'
							: playoutReach.state === 'unconfigured'
								? 'not configured'
								: 'checking…'}
				</StatusLamp>
			</div>
			<div class="flex items-center justify-between gap-3 px-4 py-1.5">
				<span class="text-sm text-muted">Schedule runner</span>
				{#if data.runner.data}
					<StatusLamp
						colour={data.runner.data.running ? 'green' : 'red'}
						quiet={data.runner.data.running}
					>
						{data.runner.data.running
							? `heartbeat ${Math.round(data.runner.data.age_seconds ?? 0)}s ago`
							: 'stopped'}
					</StatusLamp>
				{:else}
					<span class="font-mono text-xs text-faint">-</span>
				{/if}
			</div>
			<div class="flex items-center justify-between gap-3 px-4 py-1.5">
				<span class="text-sm text-muted">Library sync</span>
				{#if data.syncing}
					<StatusLamp colour="blue" pending>
						{data.syncing.name}
						<span class="font-mono text-faint">
							{Math.round(data.syncing.active_job?.percentage ?? 0)}%
						</span>
					</StatusLamp>
				{:else}
					<StatusLamp colour="neutral" quiet>
						{data.lastSync ? `idle · ${relativeTime(data.lastSync)}` : 'never run'}
					</StatusLamp>
				{/if}
			</div>
			{#if data.problems.length}
				{#each data.problems.slice(0, 2) as problem (problem.key)}
					<div class="flex items-center justify-between gap-3 px-4 py-1.5">
						<span class="min-w-0 truncate text-sm text-muted">{problem.label}</span>
						<StatusLamp colour={problem.status === 'error' ? 'red' : 'amber'}>
							<span class="max-w-72 truncate">{problem.detail}</span>
						</StatusLamp>
					</div>
				{/each}
			{:else if data.health.data}
				<div class="flex items-center justify-between gap-3 px-4 py-1.5">
					<span class="text-sm text-muted">Health checks</span>
					<StatusLamp colour="green" quiet>
						{data.health.data.checks.length} passing · v{data.health.data.version}
					</StatusLamp>
				</div>
			{:else}
				<div class="px-4 py-1.5"><Spinner size="sm" label="Checking system health…" /></div>
			{/if}
		</div>
	</Card>
</div>
