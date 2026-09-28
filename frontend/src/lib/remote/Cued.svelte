<script lang="ts">
	// Cued, not yet started: what's about to play, and the one Start.
	import { Play } from '@lucide/svelte';
	import { formatClock } from '$lib/format';
	import { formatLongRuntime } from '$lib/programmes/helpers';
	import FeatureStack from '$lib/components/FeatureStack.svelte';
	import StatusLamp from '$lib/components/StatusLamp.svelte';
	import Button from '$lib/components/ui/Button.svelte';

	interface Props {
		name: string;
		films: { id: number; title: string; thumbnail_url?: string | null }[];
		/** Programme length in seconds. */
		total: number;
		count: number;
		firstUp: string | null;
		holding: string;
		starting: boolean;
		onstart: () => void;
	}
	let { name, films, total, count, firstUp, holding, starting, onstart }: Props = $props();

	const endsAt = $derived(total ? formatClock(new Date(Date.now() + total * 1000)) : null);
</script>

<section class="border border-border bg-surface-2 p-5">
	<div class="flex items-center gap-5">
		<FeatureStack {films} size="md" />
		<div class="min-w-0 flex-1">
			<h2 class="text-2xl leading-tight font-semibold">{name}</h2>
			<p class="mt-1.5 font-mono text-xs text-muted">
				{formatLongRuntime(Math.round(total / 60))} · {count} item{count === 1 ? '' : 's'}
				{#if endsAt}· ends ~{endsAt} if started now{/if}
			</p>
			{#if firstUp}
				<p class="mt-1 truncate text-sm text-muted">
					First up: <span class="text-text">{firstUp}</span>
				</p>
			{/if}
		</div>
	</div>
	<div class="mt-5 flex flex-wrap items-center gap-4">
		<Button variant="primary" size="lg" disabled={starting} onclick={onstart}>
			<Play size={16} />
			{starting ? 'Starting…' : 'Start programme'}
		</Button>
		<StatusLamp colour="neutral" quiet>Holding on the {holding}</StatusLamp>
	</div>
</section>
