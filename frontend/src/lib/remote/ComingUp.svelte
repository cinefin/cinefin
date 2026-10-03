<script lang="ts">
	// The screenings still to play, soonest first: the remote's right-hand column on standby,
	// where the running order sits once something is cued. Each can be cued now.
	import { CalendarClock } from '@lucide/svelte';
	import { base } from '$app/paths';
	import { dayLabel, formatClock, formatRuntime } from '$lib/format';
	import FeatureStack from '$lib/components/FeatureStack.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import type { Upcoming } from './upcoming.svelte';

	interface Props {
		upcoming: Upcoming;
		/** Cue it now; absent while cueing isn't allowed. */
		oncue?: (programmeId: number) => void;
		/** Shown in the banner already. */
		skip?: number | null;
	}
	let { upcoming, oncue, skip = null }: Props = $props();

	const MAX = 6;
	const rows = $derived(upcoming.screenings.filter((s) => s.id !== skip).slice(0, MAX));
</script>

<section class="border border-border bg-surface-1">
	<header class="flex items-center justify-between gap-3 border-b border-border px-4 py-2.5">
		<h2 class="inline-flex items-center gap-1.5 text-[0.8rem] font-medium text-muted">
			<CalendarClock size={13} /> Coming up
		</h2>
		<a href="{base}/schedules" class="text-xs text-muted hover:text-text">Schedules</a>
	</header>
	{#if !upcoming.schedules.data && upcoming.schedules.loading}
		<p class="px-4 py-6 text-center text-xs text-faint">Loading…</p>
	{:else if !rows.length}
		<EmptyState
			icon={CalendarClock}
			title={skip != null ? 'Nothing else scheduled' : 'Nothing scheduled'}
			message="Screenings you schedule show here, ready to cue."
			compact
		/>
	{:else}
		<ul>
			{#each rows as s (s.id)}
				{@const plays = new Date(s.play_time)}
				{@const runtime = upcoming.runtime(s.programme.id)}
				<li class="flex items-center gap-3 border-b border-border px-3 py-2.5 last:border-b-0">
					<FeatureStack films={upcoming.features(s.programme.id)} class="w-[4.75rem] shrink-0" />
					<span class="min-w-0 flex-1">
						<span class="block truncate text-sm font-medium">{s.programme.name}</span>
						<span class="block text-xs text-muted">
							{dayLabel(plays)} <span class="font-mono">{formatClock(plays)}</span>
							{#if runtime}<span class="text-faint"> · {formatRuntime(runtime)}</span>{/if}
						</span>
					</span>
					{#if oncue}
						<Button size="sm" variant="ghost" onclick={() => oncue(s.programme.id)}>Cue</Button>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}
</section>
