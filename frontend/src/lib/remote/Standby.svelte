<script lang="ts">
	// Standby: what is on screen, the status line, the next screening (cue it now) and the
	// cue picker.
	import { dayLabel, formatClock } from '$lib/format';
	import CueDialog from '$lib/playout/CueDialog.svelte';
	import OnScreen from '$lib/playout/OnScreen.svelte';
	import { can, type PlayoutStatus } from '$lib/playout/phase';
	import { playout } from '$lib/stores/playout.svelte';
	import { showToast } from '$lib/toast.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Switch from '$lib/components/ui/Switch.svelte';

	interface Props {
		status: PlayoutStatus;
		oncued: () => void;
	}
	let { status, oncued }: Props = $props();

	const next = $derived(status.next_screening ?? null);
	const plays = $derived(next ? new Date(next.start_time) : null);
	const cues = $derived(next ? new Date(next.cue_time) : null);

	let cueOpen = $state(false);
	let cueDlg = $state<CueDialog>();

	async function statusLine(show: boolean) {
		try {
			await playout.setStatusLine(show);
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Could not change the status line', 'error');
		}
	}
</script>

<CueDialog bind:this={cueDlg} bind:open={cueOpen} {oncued} />

<section class="space-y-4">
	<div class="space-y-2.5">
		<p class="font-mono text-xs text-faint">On screen · {status.player?.name ?? 'Player'}</p>
		<OnScreen {status} class="aspect-video max-w-xl" />
		<p class="text-sm text-muted">{status.screen}, held</p>
		{#if status.player}
			<div class="flex h-11 max-w-xl items-center border-y border-border">
				<Switch
					class="w-full flex-row-reverse justify-between text-sm"
					label="Status line on the screen"
					checked={status.player.show_status}
					onchange={(show) => void statusLine(show)}
				/>
			</div>
		{/if}
	</div>

	{#if next && plays && cues}
		<div class="max-w-xl space-y-1.5 border border-border bg-surface-1 p-3.5">
			<p class="font-mono text-xs text-faint">Next screening</p>
			<p class="truncate text-base font-semibold">{next.programme_name}</p>
			<p class="text-sm text-muted">
				{dayLabel(plays)}
				<span class="font-mono">{formatClock(plays)}</span>
				{#if cues < plays}· the lead-in cues it at <span class="font-mono">{formatClock(cues)}</span
					>{/if}
			</p>
			<Button
				class="mt-1 w-full sm:w-auto"
				disabled={!can(status, 'cue')}
				onclick={() => void cueDlg?.cue(next.programme_id)}
			>
				Cue it now
			</Button>
		</div>
	{/if}

	<div class="max-w-xl space-y-2">
		<Button
			variant="primary"
			size="lg"
			class="w-full"
			disabled={!can(status, 'cue')}
			onclick={() => (cueOpen = true)}
		>
			Cue a programme
		</Button>
		<p class="text-center text-xs text-faint">Nothing is loaded. The player is on standby.</p>
	</div>
</section>
