<script lang="ts">
	// Standby: the next screening as the banner (its features' poster), cue it now or cue
	// another programme, and what the screen shows meanwhile with the status line switch.
	// There is no picture of the screen: on standby it only ever holds the ident.
	import { dayLabel, formatClock, formatRuntime } from '$lib/format';
	import { can, type PlayoutStatus } from '$lib/playout/phase';
	import { playout } from '$lib/stores/playout.svelte';
	import { showToast } from '$lib/toast.svelte';
	import StatusLamp from '$lib/components/StatusLamp.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Switch from '$lib/components/ui/Switch.svelte';
	import NowPlaying from './NowPlaying.svelte';
	import type { Upcoming } from './upcoming.svelte';

	interface Props {
		status: PlayoutStatus;
		upcoming: Upcoming;
		/** Cue a programme: the one given now, else the picker. */
		oncue: (programmeId?: number) => void;
	}
	let { status, upcoming, oncue }: Props = $props();

	const next = $derived(status.next_screening ?? null);
	const plays = $derived(next ? new Date(next.start_time) : null);
	const cues = $derived(next ? new Date(next.cue_time) : null);
	const canCue = $derived(can(status, 'cue'));

	async function statusLine(show: boolean) {
		try {
			await playout.setStatusLine(show);
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Could not change the status line', 'error');
		}
	}
</script>

<section class="border border-border bg-surface-2">
	{#if next && plays && cues}
		{@const films = upcoming.features(next.programme_id)}
		{@const runtime = upcoming.runtime(next.programme_id)}
		<NowPlaying
			art={upcoming.art(next.programme_id)}
			type="movie"
			badge="Next screening"
			title={next.programme_name}
			kicker="{dayLabel(plays)} {formatClock(plays)}{cues < plays
				? ` · the lead-in cues it at ${formatClock(cues)}`
				: ''}"
			facts={[
				films.length ? films.map((f) => f.title).join(', ') : '',
				runtime ? formatRuntime(runtime) : ''
			].filter(Boolean)}
		/>
		<div class="flex flex-wrap gap-2 p-4">
			<Button
				variant="primary"
				size="lg"
				disabled={!canCue}
				onclick={() => oncue(next.programme_id)}
			>
				Cue it now
			</Button>
			<Button size="lg" disabled={!canCue} onclick={() => oncue()}>Cue another programme</Button>
		</div>
	{:else}
		<div class="space-y-3 p-5">
			<h2 class="text-2xl leading-tight font-semibold">Nothing is loaded</h2>
			<p class="text-sm text-muted">Nothing is scheduled either. Cue a programme to play it now.</p>
			<Button variant="primary" size="lg" disabled={!canCue} onclick={() => oncue()}>
				Cue a programme
			</Button>
		</div>
	{/if}

	<!-- What the audience sees meanwhile. -->
	<div class="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-border px-4 py-3 text-sm">
		<StatusLamp colour="neutral">
			On screen: {status.screen}, held{status.player ? ` on ${status.player.name}` : ''}
		</StatusLamp>
		{#if status.player}
			<Switch
				class="ml-auto text-sm"
				label="Status line"
				checked={status.player.show_status}
				onchange={(show) => void statusLine(show)}
			/>
		{/if}
	</div>
</section>
