<script lang="ts">
	// System health in the chrome: a quiet icon while everything passes, a lamp
	// with a count once something fails. The panel lists every check, problems
	// first, each with its fix and a "Check again".
	import { HeartPulse } from '@lucide/svelte';
	import { relativeTime } from '$lib/format';
	import { health, type HealthCheck } from '$lib/stores/health.svelte';
	import StatusLamp from '$lib/components/StatusLamp.svelte';

	$effect(() => health.subscribe());

	let open = $state(false);
	let root: HTMLDivElement | undefined = $state();

	const problems = $derived(health.problems);
	const worst = $derived(problems[0]?.status === 'error' ? 'red' : 'amber');
	const rest = $derived(health.checks.filter((c) => !problems.includes(c)));

	const LAMP: Record<string, 'green' | 'amber' | 'red' | 'neutral'> = {
		ok: 'green',
		warn: 'amber',
		error: 'red'
	};
	const lamp = (c: HealthCheck) => LAMP[c.status] ?? 'neutral';

	function onWindowClick(e: MouseEvent) {
		if (open && root && !root.contains(e.target as Node)) open = false;
	}
	function onKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') open = false;
	}
</script>

<svelte:window onclick={onWindowClick} onkeydown={onKeydown} />

<div class="relative" bind:this={root}>
	<button
		type="button"
		class="flex items-center rounded-md p-1.5 text-muted hover:bg-surface-2 hover:text-text"
		aria-label={problems.length
			? `System health: ${problems.length} need attention`
			: 'System health'}
		aria-expanded={open}
		onclick={() => (open = !open)}
	>
		{#if problems.length}
			<StatusLamp colour={worst} quiet>
				{problems.length}
				{problems.length === 1 ? 'issue' : 'issues'}
			</StatusLamp>
		{:else}
			<HeartPulse size={16} />
		{/if}
	</button>

	{#if open}
		<div
			class="absolute right-0 z-20 mt-2 w-80 max-w-[calc(100vw-2rem)] rounded-md border border-border-strong bg-surface-1"
		>
			<div class="flex items-center gap-2 border-b border-border px-3 py-2 text-xs">
				<span class="font-medium">System health</span>
				{#if health.report}
					<span class="text-faint">checked {relativeTime(health.report.checked_at)}</span>
				{/if}
				<button
					type="button"
					class="ml-auto text-muted hover:text-text"
					onclick={() => void health.refresh()}
				>
					Check all
				</button>
			</div>

			<div class="max-h-[70vh] overflow-y-auto">
				{#if !health.report}
					<p class="px-3 py-3 text-xs text-muted">Checking…</p>
				{/if}
				{#each problems as check (check.key)}
					<div class="border-b border-border px-3 py-2.5">
						<StatusLamp colour={lamp(check)}>{check.label}</StatusLamp>
						<p class="mt-1 text-xs text-muted">{check.detail}</p>
						{#if check.hint}
							<p class="mt-0.5 text-xs text-faint">{check.hint}</p>
						{/if}
						<div class="mt-2 flex items-center gap-3 text-xs">
							{#if check.action}
								<a
									class="font-medium text-accent hover:underline"
									href={check.action.href}
									onclick={() => (open = false)}
								>
									{check.action.label}
								</a>
							{/if}
							<button
								type="button"
								class="text-muted hover:text-text disabled:opacity-50"
								disabled={health.rechecking === check.key}
								onclick={() => void health.recheck(check.key)}
							>
								{health.rechecking === check.key ? 'Checking…' : 'Check again'}
							</button>
						</div>
					</div>
				{/each}
				{#each rest as check (check.key)}
					{#snippet row()}
						<StatusLamp colour={lamp(check)} quiet class="shrink-0 whitespace-nowrap"
							>{check.label}</StatusLamp
						>
						<span class="ml-auto min-w-0 truncate text-[0.7rem] text-faint">{check.detail}</span>
					{/snippet}
					{#if check.action}
						<a
							href={check.action.href}
							class="flex items-center gap-3 px-3 py-1.5 hover:bg-surface-2"
							title="{check.detail} — {check.action.label}"
							onclick={() => (open = false)}>{@render row()}</a
						>
					{:else}
						<div class="flex items-center gap-3 px-3 py-1.5" title={check.detail}>
							{@render row()}
						</div>
					{/if}
				{/each}
			</div>
		</div>
	{/if}
</div>
