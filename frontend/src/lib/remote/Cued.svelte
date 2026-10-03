<script lang="ts">
	// Cued, not started: when it starts, what is on screen until then, and the one Start.
	// The running order (title card marked pre-show) is the rundown beside it.
	import { Play, Square } from '@lucide/svelte';
	import { formatClock, formatTime } from '$lib/format';
	import { untilLabel } from '$lib/dashboard/data.svelte';
	import OnScreen from '$lib/playout/OnScreen.svelte';
	import { can, cuedBy, type PlayoutStatus } from '$lib/playout/phase';
	import Button from '$lib/components/ui/Button.svelte';

	interface Props {
		status: PlayoutStatus;
		starting: boolean;
		onstart: () => void;
		onend: () => void;
	}
	let { status, starting, onstart, onend }: Props = $props();

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

<section class="max-w-xl space-y-3.5">
	<div>
		<h2 class="text-xl leading-tight font-semibold">{status.programme?.name}</h2>
		<p class="mt-1 text-sm text-muted">
			{[when, `${count} item${count === 1 ? '' : 's'}`, total ? formatTime(total) : '']
				.filter(Boolean)
				.join(' · ')}
		</p>
	</div>
	<OnScreen {status} />
	<p class="text-sm text-muted">On screen · {status.screen}, held until Start</p>
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
</section>
