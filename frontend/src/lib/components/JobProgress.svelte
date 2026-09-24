<script lang="ts">
	import { api } from '$lib/api/client';
	import { JobStream, jobIsActive, type ApiJob, type JobCounts, type JobEvent } from '$lib/jobs';
	import { showToast } from '$lib/toast.svelte';
	import { CheckCircle2, CircleAlert, X } from '@lucide/svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import ChaseMark from '$lib/components/ChaseMark.svelte';

	/** Live job progress for the Trailers page — follows one job kind on the shared WebSocket and
	 *  renders it as a state Badge, chase/meter, and a one-line receipt. Streaming failures degrade
	 *  quietly. */

	interface Props {
		kind: 'sync' | 'trailer';
		/** Server-side stream filter + cancel target (sync sources only). */
		sourceId?: number | null;
		/** Externally-loaded job to display; a new reference replaces the content, null clears it. */
		job?: ApiJob | null;
		/** Whether the card adopts a stream event. Non-followed events still reach onevent. */
		follow?: (p: JobEvent) => boolean;
		opLabels?: Record<string, string>;
		showCancel?: boolean;
		/** Offer a dismiss control on a finished job. */
		ondismiss?: () => void;
		/** Every state/progress event, before the follow filter. */
		onevent?: (p: JobEvent) => void;
		/** Every complete event, before the follow filter. */
		oncomplete?: (p: JobEvent) => void;
		/** Stream (re)connected — reconcile page state against the DB here. */
		onopen?: () => void;
		class?: string;
	}

	let {
		kind,
		sourceId = null,
		job = undefined,
		follow,
		opLabels = {},
		showCancel = true,
		ondismiss,
		onevent,
		oncomplete,
		onopen,
		class: cls = ''
	}: Props = $props();

	interface Head {
		operation: string;
		state: string;
		phase: string | null;
		total: number | null;
		current: number;
		percentage: number;
		current_item: string | null;
		counts: JobCounts;
		error?: string | null;
		source_id?: number | null;
	}

	let jobId = $state<number | null>(null);
	let header = $state<Head | null>(null);
	let cancelBusy = $state(false);

	const active = $derived(header !== null && jobIsActive(header.state));
	const determinate = $derived(!!(header && header.total));
	const pct = $derived(header && header.total ? Math.max(0, Math.min(100, header.percentage)) : 0);

	function label(op?: string | null): string {
		return (op && opLabels[op]) || op || 'Job';
	}

	const stateWord: Record<string, string> = {
		queued: 'Queued',
		running: 'Running',
		cancelling: 'Cancelling',
		success: 'Done',
		partial: 'Partial',
		cancelled: 'Cancelled',
		failed: 'Failed'
	};

	const stateVariant: Record<string, 'default' | 'accent' | 'success' | 'warning' | 'danger'> = {
		queued: 'default',
		running: 'accent',
		cancelling: 'warning',
		success: 'success',
		partial: 'warning',
		cancelled: 'warning',
		failed: 'danger'
	};

	// ---- the receipt: numeric count buckets, in a stable order --------------
	const COUNT_ORDER = ['added', 'updated', 'skipped', 'removed', 'unmatched', 'failed'];
	const receipt = $derived.by(() => {
		const c = header?.counts ?? {};
		const known = COUNT_ORDER.filter((k) => typeof c[k] === 'number' && (c[k] as number) > 0).map(
			(k) => ({ key: k, value: c[k] as number })
		);
		const extra = Object.entries(c)
			.filter(
				([k, v]) => !COUNT_ORDER.includes(k) && k !== 'changes' && typeof v === 'number' && v > 0
			)
			.map(([key, value]) => ({ key, value: value as number }));
		return [...known, ...extra];
	});
	/** "12 added · 3 updated" — the receipt as one mono line, like the sync card. */
	const receiptText = $derived(receipt.map((r) => `${r.value} ${r.key}`).join(' · '));

	// ---- externally-supplied job -------------------------------------------
	$effect(() => {
		const j = job;
		if (j === undefined) return;
		if (j === null) {
			jobId = null;
			header = null;
			return;
		}
		jobId = j.id;
		header = {
			operation: j.operation,
			state: j.state,
			phase: j.phase,
			total: j.total,
			current: j.current,
			percentage: j.percentage,
			current_item: j.current_item,
			counts: j.counts ?? {},
			error: j.error,
			source_id: j.source_id
		};
	});

	// ---- stream -------------------------------------------------------------
	$effect(() => {
		const stream = new JobStream(
			{ kind, sourceId: sourceId ?? undefined },
			{
				onState: onJobEvent,
				onProgress: onJobEvent,
				onComplete: onCompleteEvent,
				onOpen: () => onopen?.()
			}
		);
		stream.open();
		return () => stream.close();
	});

	function follows(p: JobEvent): boolean {
		return follow ? follow(p) : true;
	}

	function applyEvent(p: JobEvent) {
		header = {
			operation: p.operation,
			state: p.state,
			phase: p.phase,
			total: p.total,
			current: p.current,
			percentage: p.percentage,
			current_item: p.current_item,
			counts: p.counts ?? {},
			error: p.error,
			source_id: p.source_id
		};
	}

	function onJobEvent(p: JobEvent) {
		onevent?.(p);
		if (!follows(p)) return;
		if (jobId !== p.job_id) {
			// Only hijack for a *new active* job, never a stale terminal one the
			// trailer-kind fallback mentions.
			if (!jobIsActive(p.state)) return;
			jobId = p.job_id;
		}
		applyEvent(p);
	}

	function onCompleteEvent(p: JobEvent) {
		oncomplete?.(p);
		if (!follows(p)) return;
		if (p.job_id === jobId) applyEvent(p);
	}

	// ---- cancel -------------------------------------------------------------
	async function cancel() {
		if (!jobId || !header) return;
		cancelBusy = true;
		try {
			if (kind === 'sync') {
				const sid = sourceId ?? header.source_id;
				if (sid == null) return;
				const res = await api.DELETE('/api/v2/sync/sources/{source_id}/runs/current', {
					params: { path: { source_id: sid } }
				});
				if (res.error !== undefined) throw new Error('Cancel failed');
			} else {
				const res = await api.POST('/api/v2/trailers/jobs/{job_id}/cancel', {
					params: { path: { job_id: jobId } }
				});
				if (res.error !== undefined) throw new Error('Cancel failed');
			}
			showToast('Cancellation requested', 'info');
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Cancel failed', 'error');
		} finally {
			cancelBusy = false;
		}
	}
</script>

{#if header}
	<section class="border border-border bg-surface-1 {cls}" aria-live="polite">
		<div class="space-y-2.5 p-3.5">
			<!-- The line: what ran, and its state as a plain badge (no lamp). -->
			<div class="flex items-center gap-2.5">
				<span class="font-medium">{label(header.operation)}</span>
				<Badge variant={stateVariant[header.state] ?? 'default'}>
					{stateWord[header.state] ?? header.state}
				</Badge>
				<span class="flex-1"></span>
				{#if active && showCancel}
					<Button size="sm" disabled={cancelBusy} onclick={cancel}>Cancel</Button>
				{:else if !active && ondismiss}
					<button
						type="button"
						class="rounded-sm p-1 text-faint hover:bg-surface-2 hover:text-text"
						aria-label="Dismiss"
						onclick={ondismiss}
					>
						<X size={14} />
					</button>
				{/if}
			</div>

			{#if active}
				<!-- While it runs: the chase mark for open-ended work, a thin meter
				     for work with a known fraction (the trailers upload bar's style). -->
				{#if determinate}
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
				<!-- Once it stops: the receipt, "did it work?" in one line. -->
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
