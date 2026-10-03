<script lang="ts">
	import PageHeader from '$lib/components/shell/PageHeader.svelte';
	// The home screen: Screen (the player now, and every screening to come) above
	// Library, beside a rail of quick actions (data in lib/dashboard/data.svelte.ts).
	import { base } from '$app/paths';
	import { MonitorPlay, Settings } from '@lucide/svelte';
	import { lamp } from '$lib/playout/phase';
	import { playout } from '$lib/stores/playout.svelte';
	import { playoutReach } from '$lib/stores/playoutReach.svelte';
	import { dayLabel, formatClock, formatRuntime, formatTime } from '$lib/format';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Banner from '$lib/components/ui/Banner.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import StatusLamp from '$lib/components/StatusLamp.svelte';
	import Tally from '$lib/components/Tally.svelte';
	import FeatureStack from '$lib/components/FeatureStack.svelte';
	import TypeBadge from '$lib/components/TypeBadge.svelte';
	import ArtBackdrop from '$lib/dashboard/ArtBackdrop.svelte';
	import GettingStarted, { type Step } from '$lib/dashboard/GettingStarted.svelte';
	import LibraryBand from '$lib/dashboard/LibraryBand.svelte';
	import QuickActions from '$lib/dashboard/QuickActions.svelte';
	import {
		DashboardData,
		SCHEDULE_BADGE,
		isToday,
		itemProgress,
		untilLabel
	} from '$lib/dashboard/data.svelte';

	const data = new DashboardData();
	$effect(() => data.start());

	$effect(() => playout.subscribe());
	$effect(() => playoutReach.subscribe());

	const prog = $derived(playout.status?.programme ?? null);
	const badge = $derived(lamp(playout.status));
	const pb = $derived(playout.status?.playback ?? null);
	const progressPct = $derived(itemProgress(pb));

	const features = $derived(prog ? (data.programmeFor(prog.id)?.movies ?? []) : []);
	// The feature playing now, when the current item is one.
	const playingFeature = $derived.by(() => {
		const item = playout.status?.current_item;
		if (item?.type !== 'movie') return null;
		const details = item.details as
			{ content_id?: number; metadata?: { thumbnail_url?: string } } | undefined;
		return { id: details?.content_id ?? null, art: details?.metadata?.thumbnail_url ?? null };
	});

	// The backdrop follows the feature, not the item: it changes when a new feature
	// starts and holds through the trailers between them.
	let featureArt = $state<{ programme: number; src: string } | null>(null);
	$effect(() => {
		if (prog && playingFeature?.art) featureArt = { programme: prog.id, src: playingFeature.art };
	});
	const heroArt = $derived.by(() => {
		if (!prog) return null;
		if (featureArt?.programme === prog.id) return featureArt.src;
		return features.find((m) => m.thumbnail_url)?.thumbnail_url ?? null;
	});
	// Random features resolve at playout, so they may not be on the programme's list.
	const stackFilms = $derived(
		features.length
			? features
			: heroArt
				? [{ id: -1, title: prog?.name ?? '', thumbnail_url: heroArt }]
				: []
	);

	const endsAt = $derived.by(() => {
		const remaining = playout.status?.playlist?.programme_remaining_time;
		return remaining ? new Date(Date.now() + remaining * 1000) : null;
	});

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

<PageHeader title="Dashboard" />

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

<!-- Screen and Library beside a rail of quick actions; the rail drops below the
     bands under xl. The bands lay out by their own width (container queries). -->
<div class="grid grid-cols-1 gap-x-8 gap-y-6 xl:grid-cols-[minmax(0,1fr)_15rem]">
	<div class="@container min-w-0">
		<h2 class="font-display text-xl">Screen</h2>
		<div class="mt-3 grid grid-cols-1 gap-3 @4xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
			<!-- `isolate`: keeps this hero's z-10 content from leaking to the root and painting
			     over the sticky topbar (also z-10). -->
			<section class="relative isolate overflow-hidden border border-border bg-surface-2">
				<ArtBackdrop src={heroArt} from="right" />
				<div
					class="relative z-10 flex h-full flex-wrap items-center gap-x-6 gap-y-4 p-4 sm:flex-nowrap sm:p-5"
				>
					{#if !playout.loaded}
						<Spinner label="Checking playout status…" />
					{:else if playout.error && !playout.status}
						<ErrorState error={playout.error} retry={() => void playout.refresh()} compact />
					{:else if prog}
						<FeatureStack
							films={stackFilms}
							currentId={playingFeature?.id}
							size="md"
							class="hidden shrink-0 sm:flex"
						/>
						<div class="min-w-0 flex-1">
							<div class="flex items-center gap-3">
								{#if badge.tally}
									<Tally label={badge.label} />
								{:else}
									<StatusLamp colour={badge.colour}>{badge.label}</StatusLamp>
								{/if}
								<span class="ml-auto shrink-0 font-mono text-2xl leading-none sm:text-3xl">
									{formatTime(pb?.position ?? 0)}
									<span class="text-sm text-faint">/ {formatTime(pb?.duration ?? 0)}</span>
								</span>
							</div>
							<a
								href="{base}/programmes/{prog.id}"
								class="mt-2 block truncate font-display text-3xl hover:text-accent"
							>
								{prog.name}
							</a>
							<p class="mt-1 flex min-w-0 items-center gap-2 text-sm text-muted">
								{#if playout.status?.current_item}
									<TypeBadge type={playout.status.current_item.type} short />
								{/if}
								<span class="min-w-0 truncate">
									{playout.status?.current_item?.title || playout.status?.screen || '-'}
								</span>
								<span class="ml-auto shrink-0 font-mono text-xs text-faint">
									{#if playout.status?.playlist?.current_position != null}
										item {playout.status.playlist.current_position + 1} of {playout.status.playlist
											.total_items}
									{/if}
									{#if endsAt}· ends {formatClock(endsAt)}{/if}
								</span>
							</p>
							<div
								class="mt-3 h-2 bg-surface-3"
								style="-webkit-mask: repeating-linear-gradient(90deg, #000 0 6px, transparent 6px 9px); mask: repeating-linear-gradient(90deg, #000 0 6px, transparent 6px 9px)"
							>
								<div class="h-full bg-text transition-[width]" style="width: {progressPct}%"></div>
							</div>
						</div>
						<div class="flex w-full shrink-0 gap-2 sm:w-auto sm:flex-col">
							<Button href="{base}/remote" size="sm" variant="primary">Open remote</Button>
						</div>
					{:else}
						<MonitorPlay size={20} class="shrink-0 text-faint" />
						<div class="min-w-0 flex-1 border-border sm:border-l sm:pl-6">
							{#if playout.status?.phase === 'offline'}
								<p class="font-display text-3xl">Player offline</p>
								<p class="mt-1 text-sm text-muted">{playout.status.label}.</p>
							{:else}
								<p class="font-display text-3xl">Nothing cued</p>
								<p class="mt-1 text-sm text-muted">The player is on standby.</p>
							{/if}
						</div>
						<div class="flex w-full shrink-0 gap-2 sm:w-auto sm:flex-col">
							<Button href="{base}/programmes" size="sm">Cue a programme</Button>
							<Button href="{base}/remote" size="sm" variant="primary">Open remote</Button>
						</div>
					{/if}
				</div>
			</section>

			<Card title="Upcoming screenings">
				{#snippet actions()}
					<a class="text-xs text-muted hover:text-text" href="{base}/schedules">All</a>
				{/snippet}
				{#if data.schedules.loading}
					<Spinner size="sm" />
				{:else if data.schedules.error}
					<ErrorState
						error={data.schedules.error}
						retry={() => void data.schedules.load()}
						compact
					/>
				{:else if !data.upcoming.length}
					<p class="text-sm text-muted">
						Nothing scheduled.
						<a class="text-accent hover:underline" href="{base}/schedules">Schedule a screening</a>.
					</p>
				{:else}
					<ul class="-mx-4 -my-1 divide-y divide-border">
						{#each data.upcoming.slice(0, 5) as s (s.id)}
							{@const start = new Date(s.play_time)}
							<li class="flex items-center gap-3 px-4 py-1.5">
								<span class="w-12 shrink-0 font-mono text-sm">{formatClock(start)}</span>
								<span class="w-16 shrink-0 text-xs text-faint">{dayLabel(start)}</span>
								<a
									href="{base}/programmes/{s.programme?.id}"
									class="min-w-0 flex-1 truncate text-sm hover:text-accent"
								>
									{s.programme?.name ?? 'Programme'}
								</a>
								{#if data.programmeFor(s.programme?.id)?.playlist_stale}
									<StatusLamp colour="amber" quiet>Playlist stale</StatusLamp>
								{/if}
								{#if s.status !== 'pending' && s.status !== 'scheduled'}
									<Badge variant={SCHEDULE_BADGE[s.status] ?? 'default'}>{s.status}</Badge>
								{:else if isToday(start)}
									<span class="shrink-0 text-xs text-faint">{untilLabel(start)}</span>
								{/if}
								<span
									class="w-16 shrink-0 text-right font-mono text-xs whitespace-nowrap text-muted"
								>
									{formatRuntime(s.runtime)}
								</span>
							</li>
						{/each}
					</ul>
				{/if}
			</Card>
		</div>

		<LibraryBand {data} />
	</div>

	<aside class="xl:sticky xl:top-20 xl:self-start">
		<h2 class="font-display text-xl">Actions</h2>
		<div class="mt-3"><QuickActions /></div>
	</aside>
</div>
