<script lang="ts">
	import { api } from '$lib/api/client';
	import { jobIsActive } from '$lib/jobs';
	import { showToast } from '$lib/toast.svelte';
	import type { TrailerJob } from '$lib/trailers/job.svelte';
	import { CheckCircle2, CircleAlert } from '@lucide/svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import ChaseMark from '$lib/components/ChaseMark.svelte';

	// Live trailer-job progress: a state Badge, chase/meter, and a one-line receipt.
	interface Props {
		/** The page's trailer job; its live head is what is shown. */
		job: TrailerJob;
		opLabels?: Record<string, string>;
	}

	let { job, opLabels = {} }: Props = $props();

	let cancelBusy = $state(false);

	const header = $derived(job.head);
	const active = $derived(header !== null && jobIsActive(header.state));
	const pct = $derived(header && header.total ? Math.max(0, Math.min(100, header.percentage)) : 0);

	function label(op?: string | null): string {
		return (op && opLabels[op]) || op || 'Job';
	}

	type Variant = 'default' | 'accent' | 'success' | 'warning' | 'danger';
	const STATES: Record<string, [string, Variant]> = {
		queued: ['Queued', 'default'],
		running: ['Running', 'accent'],
		cancelling: ['Cancelling', 'warning'],
		success: ['Done', 'success'],
		partial: ['Partial', 'warning'],
		cancelled: ['Cancelled', 'warning'],
		failed: ['Failed', 'danger']
	};

	// The receipt: numeric count buckets in a stable order, then any extras ("12 added · 3 updated").
	const COUNT_ORDER = ['added', 'updated', 'skipped', 'removed', 'unmatched', 'failed'];
	const receiptText = $derived.by(() => {
		const c = header?.counts ?? {};
		const keys = [...COUNT_ORDER, ...Object.keys(c).filter((k) => !COUNT_ORDER.includes(k))];
		return keys
			.filter((k) => k !== 'changes' && typeof c[k] === 'number' && (c[k] as number) > 0)
			.map((k) => `${c[k]} ${k}`)
			.join(' · ');
	});

	async function cancel() {
		const jobId = job.headId;
		if (!jobId || !header) return;
		cancelBusy = true;
		try {
			const res = await api.POST('/api/v2/trailers/jobs/{job_id}/cancel', {
				params: { path: { job_id: jobId } }
			});
			if (res.error !== undefined) throw new Error('Cancel failed');
			showToast('Cancellation requested', 'info');
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Cancel failed', 'error');
		} finally {
			cancelBusy = false;
		}
	}
</script>

{#if header}
	<section class="border border-border bg-surface-1" aria-live="polite">
		<div class="space-y-2.5 p-3.5">
			<div class="flex items-center gap-2.5">
				<span class="font-medium">{label(header.operation)}</span>
				<Badge variant={STATES[header.state]?.[1] ?? 'default'}>
					{STATES[header.state]?.[0] ?? header.state}
				</Badge>
				<span class="flex-1"></span>
				{#if active}<Button size="sm" disabled={cancelBusy} onclick={cancel}>Cancel</Button>{/if}
			</div>

			{#if active}
				{#if header.total}
					<div class="h-1.5 overflow-hidden rounded-xs bg-surface-3">
						<div class="h-full bg-accent transition-[width]" style="width: {pct}%"></div>
					</div>
					<p class="flex items-center gap-2 font-mono text-xs text-muted">
						<span>{header.phase || label(header.operation)}</span>
						<span class="text-faint">·</span>
						<span>{header.current} / {header.total}</span>
						<span class="text-faint">·</span>
						<span>{Math.round(pct)}%</span>
						{#if header.current_item}
							<span class="min-w-0 truncate text-faint">{header.current_item}</span>
						{/if}
					</p>
				{:else}
					<p class="flex items-center gap-2 text-sm">
						<ChaseMark height={14} />
						<span>{header.phase || label(header.operation)}</span>
						{#if header.current_item}
							<span class="min-w-0 truncate text-muted">{header.current_item}</span>
						{/if}
					</p>
				{/if}
			{:else}
				<p class="flex items-center gap-1.5 text-sm">
					{#if header.state === 'success'}
						<CheckCircle2 size={14} class="shrink-0 text-success" />
					{:else}
						<CircleAlert size={14} class="shrink-0 text-danger" />
					{/if}
					{#if header.state === 'failed' && header.error}
						<span class="min-w-0 break-words text-muted">{header.error.split('\n')[0]}</span>
					{:else if receiptText}
						<span class="font-mono text-xs text-muted">{receiptText}</span>
					{:else}
						<span class="text-muted">
							{header.state === 'success'
								? 'Nothing to change - already up to date.'
								: 'No changes.'}
						</span>
					{/if}
				</p>
			{/if}
		</div>
	</section>
{/if}
