<script lang="ts">
	// Cued, not started: the programme as the banner (its first feature's poster), when it
	// starts, and the one Start. The running order (title card marked pre-show) is beside it.
	import { Play, Square } from '@lucide/svelte';
	import { formatClock, formatTime } from '$lib/format';
	import { untilLabel } from '$lib/dashboard/data.svelte';
	import { can, cuedBy, type PlayoutStatus } from '$lib/playout/phase';
	import StatusLamp from '$lib/components/StatusLamp.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import NowPlaying from './NowPlaying.svelte';

	interface Props {
		status: PlayoutStatus;
		/** The first feature's poster. */
		art?: string | null;
		starting: boolean;
		onstart: () => void;
		onend: () => void;
	}
	let { status, art = null, starting, onstart, onend }: Props = $props();

	const total = $derived(status.playlist?.programme_total_duration ?? 0);
	const count = $derived(status.playlist?.total_items ?? 0);
	// When the screening whose lead-in cued it plays, else when it would end if started now.
	const when = $derived.by(() => {
		const s = cuedBy(status);
		if (s) {
			const plays = new Date(s.start_time);
			return `Starts ${formatClock(plays)}, ${untilLabel(plays)}`;
		}
		return total ? `Ends ~${formatClock(new Date(Date.now() + total * 1000))} if started now` : '';
	});
</script>

<section class="border border-border bg-surface-2">
	<NowPlaying
		{art}
		type="movie"
		badge="Cued"
		title={status.programme?.name ?? ''}
		kicker={when || 'Ready to start'}
		facts={[`${count} item${count === 1 ? '' : 's'}`, total ? formatTime(total) : ''].filter(
			Boolean
		)}
	/>
	<div class="space-y-3 p-4">
		<Button
			variant="primary"
			size="lg"
			class="w-full"
			disabled={starting || !can(status, 'start')}
			onclick={onstart}
		>
			<Play size={16} />
			{starting ? 'Starting…' : 'Start'}
		</Button>
		<Button variant="danger" class="w-full" disabled={!can(status, 'end')} onclick={onend}>
			<Square size={12} /> End programme
		</Button>
	</div>
	<div class="border-t border-border px-4 py-3 text-sm">
		<StatusLamp colour="green">On screen: {status.screen}, held until Start</StatusLamp>
	</div>
</section>
