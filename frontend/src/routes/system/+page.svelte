<script lang="ts">
	import { ArrowRight, Copy, RefreshCw } from '@lucide/svelte';
	import { api, fetchJson, toApiError, unwrap } from '$lib/api/client';
	import { query } from '$lib/api/query.svelte';
	import { sortRows } from '$lib/filters';
	import type { components } from '$lib/api/types.gen';
	import { showToast } from '$lib/toast.svelte';
	import SortHeader from '$lib/components/SortHeader.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import StatusLamp from '$lib/components/StatusLamp.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';

	type HealthReport = components['schemas']['HealthReportSchema'];
	type HealthCheck = components['schemas']['HealthCheckSchema'];

	/** /system/update-check — plain Django JSON (views.update_check_view). */
	interface UpdateCheck {
		update_available: boolean;
		latest: string | null;
		url: string | null;
		checked_at: string;
	}

	// The report probes the printer, the playout agent, disks… so it is the
	// one deliberately "slow" read in the app. Kept fresh gently while the page
	// is open (and refetched the moment the tab comes back), so it can be left
	// up while fixing something and watched go green.
	const health = query<HealthReport>(() => unwrap(api.GET('/api/v2/system/health')));
	$effect(() => health.live({ everyMs: 30_000 }));

	// Best-effort and quiet: the view never errors, but the fetch can.
	const update = query(() => fetchJson<UpdateCheck>('/system/update-check'));

	// ---- status vocabulary -----------------------------------------------------
	const STATUS_LABEL: Record<string, string> = {
		ok: 'OK',
		warn: 'Warning',
		error: 'Problem',
		info: 'Info'
	};
	// Statuses are lamps beside words (spec §06 C3), not tinted capsules.
	const STATUS_LAMP: Record<string, 'green' | 'amber' | 'red' | 'neutral'> = {
		ok: 'green',
		warn: 'amber',
		error: 'red',
		info: 'neutral'
	};
	const OVERALL: Record<string, { label: string; dot: string }> = {
		ok: { label: 'Everything looks OK', dot: 'bg-success' },
		warn: { label: 'Some things need attention', dot: 'bg-warning' },
		error: { label: 'Something needs fixing', dot: 'bg-danger' }
	};
	const RANK: Record<string, number> = { error: 0, warn: 1, ok: 2, info: 2 };

	const overall = $derived(OVERALL[health.data?.overall ?? ''] ?? OVERALL.ok);

	// Triage order: problems first, then warnings, then the fine ones in the
	// service's own order (stable sort keeps that).
	const checks = $derived(
		[...(health.data?.checks ?? [])].sort((a, b) => (RANK[a.status] ?? 2) - (RANK[b.status] ?? 2))
	);
	const problemCount = $derived(
		checks.filter((c) => c.status === 'error' || c.status === 'warn').length
	);

	// Click-to-sort; empty keeps the triage order. Status sorts by severity.
	let sort = $state('');
	const rows = $derived(
		sort
			? sortRows(checks, sort, {
					check: (c) => c.label?.toLowerCase(),
					status: (c) => RANK[c.status] ?? 2
				})
			: checks
	);

	// "Checked 42 s ago", ticking so the poll is visibly alive.
	let now = $state(Date.now());
	$effect(() => {
		const t = setInterval(() => (now = Date.now()), 5_000);
		return () => clearInterval(t);
	});
	const checkedAgo = $derived.by(() => {
		if (!health.data?.checked_at) return '';
		const then = new Date(health.data.checked_at).getTime();
		if (Number.isNaN(then)) return '';
		const secs = Math.max(0, Math.round((now - then) / 1000));
		if (secs < 5) return 'just now';
		if (secs < 90) return `${secs} s ago`;
		return `${Math.round(secs / 60)} min ago`;
	});
	const checkedAtFull = $derived(
		health.data?.checked_at ? new Date(health.data.checked_at).toLocaleString() : ''
	);

	// ---- per-row re-check ------------------------------------------------------
	let rechecking = $state<Record<string, boolean>>({});

	async function recheck(key: string) {
		if (!health.data || rechecking[key]) return;
		rechecking[key] = true;
		try {
			const fresh = await unwrap(
				api.GET('/api/v2/system/health/checks/{key}', { params: { path: { key } } })
			);
			if (!health.data) return;
			const merged = health.data.checks.map((c) => (c.key === key ? fresh : c));
			health.data = {
				...health.data,
				checks: merged,
				overall: worstOf(merged),
				checked_at: new Date().toISOString()
			};
		} catch (e) {
			showToast(toApiError(e).message || 'Could not re-run the check', 'error');
		} finally {
			rechecking[key] = false;
		}
	}

	function worstOf(list: HealthCheck[]): string {
		let worst = 'ok';
		for (const c of list) {
			if (c.status === 'error') return 'error';
			if (c.status === 'warn') worst = 'warn';
		}
		return worst;
	}

	// ---- copy diagnostic report ------------------------------------------------
	async function copyReport() {
		const r = health.data;
		if (!r) return;
		const lines = [
			'Cinefin diagnostic report',
			`Version:  ${r.version || 'unknown'}`,
			`Overall:  ${STATUS_LABEL[r.overall] ?? r.overall}`,
			`Checked:  ${checkedAtFull}`,
			''
		];
		for (const c of r.checks) {
			lines.push(`[${(STATUS_LABEL[c.status] ?? c.status).toUpperCase()}] ${c.label}`);
			if (c.detail) lines.push(`    ${c.detail}`);
			if (c.hint) lines.push(`    hint: ${c.hint}`);
		}
		try {
			await navigator.clipboard.writeText(lines.join('\n'));
			showToast('Diagnostic report copied', 'success');
		} catch {
			showToast('Could not copy to clipboard', 'error');
		}
	}

	// ---- version block ---------------------------------------------------------
	const isRelease = $derived(/^v\d+\.\d+\.\d+$/.test(health.data?.version ?? ''));

	// Health check action links point at app paths ("/app/settings"); render
	// them as-is — they are already SPA URLs.
</script>

<svelte:head>
	<title>System</title>
</svelte:head>

<div class="mb-1 flex flex-wrap items-center gap-2">
	<h1 class="mr-auto text-lg font-semibold">System</h1>
	<Button size="sm" onclick={copyReport} disabled={!health.data} title="Copy a plain-text report">
		<Copy size={14} /> Copy report
	</Button>
	<Button size="sm" onclick={() => void health.load()} disabled={health.loading}>
		<RefreshCw size={14} />
		{health.loading ? 'Refreshing…' : 'Refresh'}
	</Button>
</div>
<p class="mb-4 text-sm text-muted">
	A quick "is everything OK?" check of the parts that matter for running screenings.
</p>

{#if health.loading && !health.data}
	<Spinner label="Running checks" />
{:else if health.error && !health.data}
	<ErrorState error={health.error} retry={() => void health.load()} />
{:else if health.data}
	<div
		class="mb-4 flex flex-wrap items-center gap-3 border border-border bg-surface-1 px-4 py-3"
		role="status"
	>
		<span class="h-2.5 w-2.5 {overall.dot}" aria-hidden="true"></span>
		<span class="text-sm font-medium">{overall.label}</span>
		{#if problemCount}
			<span class="text-sm text-muted">{problemCount} of {checks.length} checks need attention</span
			>
		{:else}
			<span class="text-sm text-muted">All {checks.length} checks passed</span>
		{/if}
		<span class="ml-auto text-xs text-faint" title={checkedAtFull}>
			Checked {checkedAgo}{#if health.error}
				<span class="text-danger"> · last refresh failed</span>{/if}
		</span>
	</div>

	<div class="grid gap-4 lg:grid-cols-[minmax(0,1fr)_18rem]">
		<section class="min-w-0 border border-border bg-surface-1">
			<header class="flex items-center justify-between border-b border-border px-3.5 py-2.5">
				<h2 class="text-[0.78125rem] font-medium text-muted">Checks</h2>
				<span class="text-xs text-muted">Refreshes every 30 s</span>
			</header>
			<div class="overflow-x-auto">
				<table class="w-full text-sm">
					<thead>
						<tr
							class="border-b border-border bg-surface-2 text-left text-xs font-medium text-muted"
						>
							<SortHeader {sort} col="check" label="Check" onsort={(s) => (sort = s)} />
							<SortHeader {sort} col="status" label="Status" onsort={(s) => (sort = s)} />
							<th class="px-3 py-2 font-medium">Detail</th>
							<th class="px-3 py-2 text-right font-medium"><span class="sr-only">Actions</span></th>
						</tr>
					</thead>
					<tbody class="divide-y divide-border">
						{#each rows as check (check.key)}
							<tr class="align-top">
								<td class="px-3 py-2.5 font-medium whitespace-nowrap">{check.label}</td>
								<td class="px-3 py-2.5">
									<StatusLamp colour={STATUS_LAMP[check.status] ?? 'neutral'}>
										{STATUS_LABEL[check.status] ?? check.status}
									</StatusLamp>
								</td>
								<td class="min-w-64 px-3 py-2.5">
									<p class="text-text">{check.detail}</p>
									{#if check.hint}
										<p class="mt-0.5 text-xs text-muted">{check.hint}</p>
									{/if}
									{#if check.action}
										<a
											href={check.action.href}
											class="mt-1 inline-flex items-center gap-1 text-xs text-accent hover:underline"
										>
											{check.action.label}
											<ArrowRight size={12} />
										</a>
									{/if}
								</td>
								<td class="px-3 py-2 text-right whitespace-nowrap">
									<Button
										size="sm"
										variant="ghost"
										onclick={() => recheck(check.key)}
										disabled={Boolean(rechecking[check.key])}
										title="Re-run this check"
									>
										<RefreshCw size={13} />
										{rechecking[check.key] ? 'Checking…' : 'Re-check'}
									</Button>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</section>

		<Card title="Version">
			<dl class="space-y-3 text-sm">
				<div>
					<dt class="text-xs text-muted">Running</dt>
					<dd class="mt-0.5 font-mono text-text">{health.data.version || 'unknown'}</dd>
					<dd class="text-xs text-faint">
						{isRelease ? 'Release build' : 'Development build'}
					</dd>
				</div>
				<div>
					<dt class="text-xs text-muted">Updates</dt>
					<dd class="mt-0.5">
						{#if update.loading}
							<span class="text-muted">Checking for updates…</span>
						{:else if update.error || !update.data}
							<span class="text-muted">Update check unavailable</span>
						{:else if update.data.update_available}
							<Badge variant="accent">Update available</Badge>
							{#if update.data.latest}
								<span class="ml-1 font-mono">{update.data.latest}</span>
							{/if}
							{#if update.data.url}
								<a
									href={update.data.url}
									target="_blank"
									rel="noopener noreferrer"
									class="mt-1 block text-xs text-accent hover:underline">Release notes</a
								>
							{/if}
						{:else if update.data.latest}
							<StatusLamp colour="green">Up to date</StatusLamp>
							<span class="ml-1 text-xs text-muted"
								>latest is <span class="font-mono">{update.data.latest}</span></span
							>
						{:else}
							<span class="text-muted">No update reported</span>
							<p class="mt-0.5 text-xs text-faint">
								The check only runs for release builds, with update checks enabled.
							</p>
						{/if}
					</dd>
				</div>
			</dl>
		</Card>
	</div>
{/if}
