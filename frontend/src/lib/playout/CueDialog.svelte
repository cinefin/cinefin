<script lang="ts" module>
	/** "2 items are unreachable and will be skipped: a; b" (the first three named). */
	export function skippedText(warnings: unknown[]): string {
		const n = warnings.length;
		return (
			`${n} item${n === 1 ? ' is' : 's are'} unreachable and will be skipped: ` +
			warnings.slice(0, 3).join('; ') +
			(n > 3 ? '…' : '')
		);
	}
</script>

<script lang="ts">
	// Cue a programme: the one picker, opened from the playout bar and the remote on standby.
	import { api, unwrap } from '$lib/api/client';
	import { Query } from '$lib/api/query.svelte';
	import { formatRuntime } from '$lib/format';
	import { playout } from '$lib/stores/playout.svelte';
	import { showToast } from '$lib/toast.svelte';
	import FeatureStack from '$lib/components/FeatureStack.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Dialog from '$lib/components/ui/Dialog.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import { ListVideo } from '@lucide/svelte';

	interface Props {
		open: boolean;
		/** After a programme is cued (the remote refreshes its running order). */
		oncued?: () => void;
	}
	let { open = $bindable(), oncued }: Props = $props();

	// Loaded when first opened, so the bar costs nothing until the picker is used.
	const programmes = new Query(() => unwrap(api.GET('/api/v2/programmes/list')));
	let requested = false;
	$effect(() => {
		if (open && !requested) {
			requested = true;
			void programmes.load();
		}
	});

	let filter = $state('');
	let cueing = $state<number | null>(null);
	const shown = $derived(
		(programmes.data?.programmes ?? []).filter((p) =>
			p.name.toLowerCase().includes(filter.trim().toLowerCase())
		)
	);

	/** Cue one programme (also the remote's "Cue it now"), toasting unreachable items. */
	export async function cue(id: number): Promise<void> {
		cueing = id;
		try {
			const warnings = await playout.cue(id);
			if (warnings.length) showToast(`Cued. ${skippedText(warnings)}`, 'warning');
			open = false;
			oncued?.();
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Failed to cue the programme', 'error');
		} finally {
			cueing = null;
		}
	}
</script>

<Dialog bind:open title="Cue a programme" size="xl">
	<div class="space-y-3 p-4">
		<Input type="search" bind:value={filter} placeholder="Find a programme" />
		{#if programmes.loading && !programmes.data}
			<Spinner label="Loading programmes…" />
		{:else if programmes.error}
			<ErrorState error={programmes.error} retry={() => void programmes.load()} compact />
		{:else if !shown.length}
			<EmptyState icon={ListVideo} title="No programmes" compact />
		{:else}
			<ul class="max-h-[60vh] divide-y divide-border overflow-y-auto border border-border">
				{#each shown as p (p.id)}
					<li class="flex items-center gap-3 px-3 py-2">
						<FeatureStack films={p.movies} />
						<div class="min-w-0 flex-1">
							<p class="truncate text-sm font-medium">{p.name}</p>
							<p class="font-mono text-xs text-faint">
								{p.total_runtime ? formatRuntime(p.total_runtime) : ''}
							</p>
						</div>
						<Button size="sm" disabled={cueing != null} onclick={() => void cue(p.id)}>
							{cueing === p.id ? 'Cueing…' : 'Cue'}
						</Button>
					</li>
				{/each}
			</ul>
		{/if}
	</div>
</Dialog>
