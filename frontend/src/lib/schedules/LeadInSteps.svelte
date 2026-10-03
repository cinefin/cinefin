<script lang="ts" module>
	/** One lead-in step: a command, or the single cue step. */
	export interface LeadInStep {
		command?: number | null;
		cue: boolean;
	}
</script>

<script lang="ts">
	// A screening's lead-in steps, in order: commands (each finishes and waits out its
	// duration) and the one cue step, which loads the programme so its title slate holds.
	import { base } from '$app/paths';
	import { ChevronDown, ChevronUp, Clapperboard, Plus, Terminal, X } from '@lucide/svelte';
	import { api, unwrap } from '$lib/api/client';
	import { formatTime } from '$lib/format';
	import { query } from '$lib/api/query.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Select from '$lib/components/ui/Select.svelte';

	// `length`: the lead-in in seconds, which the commands' durations are measured against.
	let { steps = $bindable(), length }: { steps: LeadInStep[]; length: number } = $props();

	const commands = query(async () => (await unwrap(api.GET('/api/v2/commands/list'))).commands);
	const commandOf = (id: number | null | undefined) => commands.data?.find((c) => c.id === id);
	const nameOf = (id: number | null | undefined) => commandOf(id)?.name ?? `Command #${id}`;
	const total = $derived(steps.reduce((sum, s) => sum + (commandOf(s.command)?.duration ?? 0), 0));

	// The cue is always present; with none stored it runs first.
	$effect(() => {
		if (!steps.some((s) => s.cue)) steps = [{ cue: true }, ...steps];
	});

	let pick = $state('');
	function add() {
		const id = parseInt(pick, 10);
		pick = '';
		if (id && !steps.some((s) => s.command === id)) steps = [...steps, { command: id, cue: false }];
	}
	function move(i: number, by: -1 | 1) {
		const list = [...steps];
		[list[i], list[i + by]] = [list[i + by], list[i]];
		steps = list;
	}

	const iconBtn =
		'shrink-0 rounded-sm p-0.5 text-muted hover:bg-surface-3 hover:text-text disabled:opacity-30';
	const MOVES = [
		{ label: 'Move up', by: -1, Icon: ChevronUp },
		{ label: 'Move down', by: 1, Icon: ChevronDown }
	] as const;
</script>

<ol class="divide-y divide-border rounded-md border border-border">
	{#each steps as step, i (step.cue ? 'cue' : step.command)}
		<li class="flex items-center gap-2 px-3 py-1.5 text-sm">
			<span class="w-4 shrink-0 text-right font-mono text-xs text-faint">{i + 1}</span>
			{#if step.cue}
				<Clapperboard size={13} class="shrink-0 text-accent" />
				<span class="min-w-0 flex-1 truncate">
					Cue the programme <span class="text-faint">· title slate holds</span>
				</span>
			{:else}
				<Terminal size={13} class="shrink-0 text-muted" />
				<span class="min-w-0 flex-1 truncate">{nameOf(step.command)}</span>
				<span class="shrink-0 font-mono text-xs text-faint">
					{formatTime(commandOf(step.command)?.duration ?? 0)}
				</span>
			{/if}
			{#each MOVES as m (m.by)}
				<button
					type="button"
					class={iconBtn}
					aria-label={m.label}
					disabled={!steps[i + m.by]}
					onclick={() => move(i, m.by)}
				>
					<m.Icon size={14} />
				</button>
			{/each}
			{#if step.cue}
				<span class="w-5 shrink-0"></span>
			{:else}
				<button
					type="button"
					class="{iconBtn} hover:text-danger"
					aria-label="Remove {nameOf(step.command)}"
					onclick={() => (steps = steps.filter((_, j) => j !== i))}
				>
					<X size={14} />
				</button>
			{/if}
		</li>
	{/each}
</ol>
{#if total}
	<p class="mt-1.5 font-mono text-xs {total > length ? 'text-warning' : 'text-faint'}">
		Commands take {formatTime(total)} of the {formatTime(length)} lead-in{total > length
			? ' — the programme will start late'
			: ''}
	</p>
{/if}
<div class="mt-2 flex gap-2">
	<Select bind:value={pick} class="w-full">
		<option value="">Add a command…</option>
		{#each commands.data ?? [] as cmd (cmd.id)}
			<option value={String(cmd.id)}>{cmd.name}</option>
		{/each}
	</Select>
	<Button onclick={add}><Plus size={14} /> Add</Button>
</div>
<p class="mt-1 text-xs text-faint">
	Each <a href="{base}/commands" class="text-accent hover:underline">command</a> finishes (and waits out
	its duration) before the next step. Move the cue below any step that must come first, such as restarting
	the player. A failing command is logged and skipped.
</p>
