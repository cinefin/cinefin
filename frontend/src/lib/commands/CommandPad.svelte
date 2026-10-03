<script lang="ts">
	// The command buttons on a surface (dashboard, remote): the commands picked on
	// this device, in order, with a "Choose…" picker. Past `max` the rest fold into More.
	import { untrack, type Snippet } from 'svelte';
	import { base } from '$app/paths';
	import { api, unwrap } from '$lib/api/client';
	import { query } from '$lib/api/query.svelte';
	import { showToast, toastFailure } from '$lib/toast.svelte';
	import Menu, { type MenuItem } from '$lib/components/ui/Menu.svelte';
	import CommandPicker from './CommandPicker.svelte';
	import { CommandPicks, type Surface } from './picks.svelte';
	import { providerIcon } from './providers';
	import type { components } from '$lib/api/types.gen';

	type Command = components['schemas']['CommandSchema'];

	interface Props {
		surface: Surface;
		/** Left of the toolbar (the surface's own heading). */
		label: Snippet;
		/** `list` — compact rows (dashboard rail); `grid` — larger buttons (remote). */
		variant?: 'list' | 'grid';
		max?: number;
	}
	let { surface, label, variant = 'list', max = Infinity }: Props = $props();

	// A pad's surface is fixed for its lifetime.
	const picks = new CommandPicks(untrack(() => surface));
	const commands = query(async () => {
		const data = await unwrap(api.GET('/api/v2/commands/list'));
		return (data?.commands ?? []) as Command[];
	});
	$effect(() => commands.invalidatesOn(['commands']));

	// Picks for commands deleted since drop out silently.
	const picked = $derived.by(() => {
		const byId = new Map((commands.data ?? []).map((c) => [c.id, c]));
		return picks.ids.map((id) => byId.get(id)).filter((c): c is Command => !!c);
	});
	const overflow = $derived<MenuItem[]>(
		picked.slice(max).map((cmd) => ({
			label: cmd.name,
			icon: providerIcon(cmd.provider_icon),
			onclick: () => void run(cmd),
			disabled: running != null
		}))
	);

	let choosing = $state(false);
	let running = $state<number | null>(null);

	async function run(cmd: Command) {
		if (running != null) return;
		running = cmd.id;
		try {
			await unwrap(
				api.POST('/api/v2/commands/{command_id}/execute', {
					params: { path: { command_id: cmd.id } }
				})
			);
			showToast(`${cmd.name} done`, 'success');
		} catch (e) {
			toastFailure(`${cmd.name} failed`, e);
		} finally {
			running = null;
		}
	}

	const BUTTON = {
		list: 'gap-2 border border-border bg-surface-1 px-2.5 py-1.5 text-xs hover:bg-surface-2',
		grid: 'gap-2 border border-border bg-surface-2 px-3 py-2.5 text-sm hover:bg-surface-3'
	};
</script>

<div class="flex h-6 items-center gap-3 text-xs text-muted">
	{@render label()}
	{#if overflow.length}
		<Menu items={overflow} label="More ({overflow.length})" size="sm" variant="ghost" />
	{/if}
	<button type="button" class="ml-auto hover:text-text" onclick={() => (choosing = true)}>
		Choose…
	</button>
</div>

{#if picked.length}
	<div
		class="mt-1.5 {variant === 'grid'
			? 'grid grid-cols-2 gap-2 sm:grid-cols-3'
			: 'flex flex-col gap-1.5'}"
	>
		{#each picked.slice(0, max) as cmd (cmd.id)}
			{@const Icon = providerIcon(cmd.provider_icon)}
			<button
				type="button"
				class="flex w-full items-center text-left transition-colors disabled:pointer-events-none disabled:opacity-50 {BUTTON[
					variant
				]}"
				disabled={running != null}
				onclick={() => void run(cmd)}
			>
				<Icon size={variant === 'grid' ? 14 : 13} class="shrink-0 text-muted" />
				<!-- A busy button disables and says so (spec M4) — no spinner. -->
				<span class="truncate">{running === cmd.id ? 'Running…' : cmd.name}</span>
			</button>
		{/each}
	</div>
{:else if commands.data}
	<p class="mt-1.5 text-xs text-faint">
		{#if commands.data.length}
			No commands on this device yet —
			<button type="button" class="text-accent hover:underline" onclick={() => (choosing = true)}>
				choose some
			</button>.
		{:else}
			No commands yet — <a class="text-accent hover:underline" href="{base}/commands">create one</a
			>.
		{/if}
	</p>
{/if}

<CommandPicker
	bind:open={choosing}
	title="Commands on the {surface}"
	commands={commands.data ?? []}
	picked={picks.ids}
	onsave={(ids) => picks.save(ids)}
/>
