<script lang="ts">
	// Quick actions for the dashboard's rail: the commands marked "show on remote"
	// (the remote's set, chosen on the Commands page — past six the rest fold into
	// More), then app shortcuts.
	import { base } from '$app/paths';
	import { CalendarPlus, Clapperboard, ListPlus } from '@lucide/svelte';
	import { api, unwrap } from '$lib/api/client';
	import { query } from '$lib/api/query.svelte';
	import { providerIcon } from '$lib/commands/providers';
	import { showToast } from '$lib/toast.svelte';
	import Menu, { type MenuItem } from '$lib/components/ui/Menu.svelte';
	import type { components } from '$lib/api/types.gen';

	type Command = components['schemas']['CommandSchema'];

	const SHOWN = 6;

	const commands = query(async () => {
		const data = await unwrap(
			api.GET('/api/v2/commands/list', { params: { query: { show_on_remote: true } } })
		);
		return (data?.commands ?? []) as Command[];
	});
	$effect(() => commands.invalidatesOn(['commands']));

	const list = $derived(commands.data ?? []);
	const overflow = $derived<MenuItem[]>(
		list.slice(SHOWN).map((cmd) => ({
			label: cmd.name,
			icon: providerIcon(cmd.provider_icon),
			onclick: () => void run(cmd),
			disabled: running != null
		}))
	);

	const SHORTCUTS = [
		{ label: 'Fetch trailers', icon: Clapperboard, href: `${base}/trailers?fetch=open` },
		{ label: 'New programme', icon: ListPlus, href: `${base}/programmes/create` },
		{ label: 'Schedule a screening', icon: CalendarPlus, href: `${base}/schedules` }
	];

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
			showToast(`${cmd.name} failed: ${e instanceof Error ? e.message : e}`, 'error');
		} finally {
			running = null;
		}
	}

	const tile =
		'flex w-full items-center gap-2 border border-border bg-surface-1 px-2.5 py-1.5 text-left text-xs transition-colors hover:bg-surface-2 disabled:pointer-events-none disabled:opacity-50';
</script>

<!-- One column in the rail; side by side (each button-width) when it drops below the bands. -->
<div class="@container">
	<div class="grid max-w-3xl grid-cols-1 items-start gap-5 @xl:grid-cols-2">
		<div>
			<div class="flex h-6 items-center gap-3 text-xs text-muted">
				<span>Commands</span>
				{#if overflow.length}
					<Menu items={overflow} label="More ({overflow.length})" size="sm" variant="ghost" />
				{/if}
				<a class="ml-auto hover:text-text" href="{base}/commands">Choose…</a>
			</div>
			{#if list.length}
				<div class="mt-1.5 flex flex-col gap-1.5">
					{#each list.slice(0, SHOWN) as cmd (cmd.id)}
						{@const Icon = providerIcon(cmd.provider_icon)}
						<button
							type="button"
							class={tile}
							disabled={running != null}
							onclick={() => void run(cmd)}
						>
							<Icon size={13} class="shrink-0 text-muted" />
							<span class="truncate">{running === cmd.id ? 'Running…' : cmd.name}</span>
						</button>
					{/each}
				</div>
			{:else if commands.data}
				<p class="mt-1.5 text-xs text-faint">
					None yet — mark commands "show on remote" to add them here.
				</p>
			{/if}
		</div>

		<div>
			<div class="flex h-6 items-center text-xs text-muted">Shortcuts</div>
			<div class="mt-1.5 flex flex-col gap-1.5">
				{#each SHORTCUTS as s (s.label)}
					<a class={tile} href={s.href}>
						<s.icon size={13} class="shrink-0 text-muted" />
						{s.label}
					</a>
				{/each}
			</div>
		</div>
	</div>
</div>
