<script lang="ts">
	// Nothing cued: the next screening (cue it now) and a picker for any programme.
	import { api, unwrap } from '$lib/api/client';
	import type { components } from '$lib/api/types.gen';
	import { dayLabel, formatClock } from '$lib/format';
	import { untilLabel } from '$lib/dashboard/data.svelte';
	import { showToast } from '$lib/toast.svelte';
	import FeatureStack from '$lib/components/FeatureStack.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Select from '$lib/components/ui/Select.svelte';

	type Programme = components['schemas']['ProgrammeListItemSchema'];
	type Schedule = components['schemas']['ScheduleSchema'];

	interface Props {
		programmes: Programme[];
		schedules: Schedule[];
		oncued: () => void;
	}
	let { programmes, schedules, oncued }: Props = $props();

	const next = $derived(
		schedules
			.filter((s) => s.status === 'scheduled' || s.status === 'pending')
			.sort((a, b) => new Date(a.start_time).getTime() - new Date(b.start_time).getTime())[0] ??
			null
	);
	const nextPlays = $derived(next ? new Date(next.play_time ?? next.start_time) : null);
	const nextFilms = $derived(
		next ? (programmes.find((p) => p.id === next.programme.id)?.movies ?? []) : []
	);

	let picked = $state('');
	let cueing = $state(false);

	async function cue(id: number) {
		cueing = true;
		try {
			await unwrap(
				api.POST('/api/v2/playout/load', { body: { programme_id: id, generate_playlist: true } })
			);
			oncued();
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Failed to cue the programme', 'error');
		} finally {
			cueing = false;
		}
	}
</script>

<section class="border border-border bg-surface-1 p-5">
	<p class="font-display text-3xl">Nothing cued</p>
	<p class="mt-1 text-sm text-muted">The player is showing the idle ident.</p>

	{#if next && nextPlays}
		<div class="mt-5 flex flex-wrap items-center gap-4 border-t border-border pt-4">
			<FeatureStack films={nextFilms} />
			<div class="min-w-0 flex-1">
				<p class="text-xs text-faint">
					Next screening · {dayLabel(nextPlays)}
					<span class="font-mono">{formatClock(nextPlays)}</span> · {untilLabel(nextPlays)}
				</p>
				<p class="truncate font-medium">{next.programme.name}</p>
			</div>
			<Button variant="primary" disabled={cueing} onclick={() => void cue(next.programme.id)}>
				Cue now
			</Button>
		</div>
	{/if}

	<div class="mt-4 flex flex-wrap items-center gap-2 border-t border-border pt-4">
		<label for="remote-cue" class="text-sm text-muted">Cue a programme</label>
		<Select id="remote-cue" bind:value={picked} class="min-w-0 flex-1 sm:max-w-sm">
			<option value="">Choose…</option>
			{#each programmes as p (p.id)}
				<option value={String(p.id)}>{p.name}</option>
			{/each}
		</Select>
		<Button disabled={!picked || cueing} onclick={() => void cue(Number(picked))}>
			{cueing ? 'Cueing…' : 'Cue'}
		</Button>
	</div>
</section>
