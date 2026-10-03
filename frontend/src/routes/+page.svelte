<script lang="ts">
	import PageHeader from '$lib/components/shell/PageHeader.svelte';
	import { base } from '$app/paths';
	import { Settings } from '@lucide/svelte';
	import { playout } from '$lib/stores/playout.svelte';
	import { playoutReach } from '$lib/stores/playoutReach.svelte';
	import { dayLabel, formatClock, formatRuntime } from '$lib/format';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Banner from '$lib/components/ui/Banner.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import StatusLamp from '$lib/components/StatusLamp.svelte';
	import NowPlaying from '$lib/playout/NowPlaying.svelte';
	import GettingStarted, { type Step } from '$lib/dashboard/GettingStarted.svelte';
	import LibraryBand from '$lib/dashboard/LibraryBand.svelte';
	import QuickActions from '$lib/dashboard/QuickActions.svelte';
	import { DashboardData, SCHEDULE_BADGE, isToday, untilLabel } from '$lib/dashboard/data.svelte';

	const data = new DashboardData();
	$effect(() => data.start());

	$effect(() => playout.subscribe());
	$effect(() => playoutReach.subscribe());

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
		// prettier-ignore
		const rows: [string, boolean, string, string, string][] = [
			['Connect the player', playoutReach.state === 'ok', 'Connected', 'settings?tab=playout', 'Set up'],
			['Sync a movie library', movies > 0, `${movies.toLocaleString()} movies`, 'library?sync=open', 'Sync'],
			['Fetch some trailers', trailers > 0, `${trailers.toLocaleString()} trailers`, 'trailers?fetch=open', 'Fetch'],
			['Build your first programme', programmes.length > 0, `${programmes.length} built`, 'programmes/new', 'Create'],
			['Put it on screen', played, 'Played', 'programmes', 'Choose one']
		];
		return rows.map(([label, done, note, path, action]) => ({
			label,
			done,
			note,
			href: `${base}/${path}`,
			action
		}));
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

<div class="grid grid-cols-1 gap-x-8 gap-y-6 xl:grid-cols-[minmax(0,1fr)_15rem]">
	<div class="@container min-w-0">
		<h2 class="font-display text-xl">Screen</h2>
		<div class="mt-3 grid grid-cols-1 gap-3 @4xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
			{#if !playout.loaded}
				<section class="border border-border bg-surface-2 p-5">
					<Spinner label="Checking playout status…" />
				</section>
			{:else if !playout.status}
				<section class="border border-border bg-surface-2 p-5">
					<ErrorState error={playout.error} retry={() => void playout.refresh()} compact />
				</section>
			{:else}
				<!-- `isolate` (in NowPlaying) keeps its content under the sticky topbar. -->
				<NowPlaying status={playout.status} address={playoutReach.hostUrl}>
					{#snippet actions()}
						{#if playout.status?.phase === 'offline'}
							<Button href="{base}/settings?tab=playout" size="sm">
								<Settings size={13} /> Player settings
							</Button>
						{:else if playout.status?.phase === 'standby'}
							<Button href="{base}/programmes" size="sm">Cue a programme</Button>
						{/if}
						<Button href="{base}/remote" size="sm" variant="primary">Open remote</Button>
					{/snippet}
				</NowPlaying>
			{/if}

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
