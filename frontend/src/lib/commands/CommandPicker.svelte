<script lang="ts">
	// Choose and order the commands a surface shows: the picked list (reorder,
	// remove) above every other command (add), with a search across both.
	import { ArrowDown, ArrowUp, Plus, X } from '@lucide/svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Dialog from '$lib/components/ui/Dialog.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import { providerIcon } from './providers';
	import type { components } from '$lib/api/types.gen';

	type Command = components['schemas']['CommandSchema'];

	interface Props {
		open: boolean;
		title: string;
		commands: Command[];
		picked: number[];
		onsave: (ids: number[]) => void;
	}
	let { open = $bindable(), title, commands, picked, onsave }: Props = $props();

	let draft = $state<number[]>([]);
	let search = $state('');
	$effect(() => {
		if (open) {
			draft = picked.filter((id) => commands.some((c) => c.id === id));
			search = '';
		}
	});

	const byId = $derived(new Map(commands.map((c) => [c.id, c])));
	const matches = (c: Command) => c.name.toLowerCase().includes(search.trim().toLowerCase());
	const chosen = $derived(draft.map((id) => byId.get(id)).filter((c): c is Command => !!c));
	const others = $derived(commands.filter((c) => !draft.includes(c.id) && matches(c)));

	function move(i: number, by: -1 | 1) {
		const next = [...draft];
		[next[i], next[i + by]] = [next[i + by], next[i]];
		draft = next;
	}

	const iconBtn =
		'rounded-sm p-1 text-muted hover:bg-surface-3 hover:text-text disabled:pointer-events-none disabled:opacity-30';
</script>

<Dialog bind:open {title}>
	<p class="text-xs text-muted">Saved on this device only.</p>

	<p class="mt-4 text-xs text-muted">Shown here, in this order</p>
	{#if chosen.length}
		<ul class="mt-1.5 divide-y divide-border border border-border">
			{#each chosen as c, i (c.id)}
				{@const Icon = providerIcon(c.provider_icon)}
				<li class="flex items-center gap-2 px-2.5 py-1.5 text-sm">
					<Icon size={13} class="shrink-0 text-muted" />
					<span class="min-w-0 flex-1 truncate">{c.name}</span>
					<button
						type="button"
						class={iconBtn}
						aria-label="Move {c.name} up"
						disabled={i === 0}
						onclick={() => move(i, -1)}><ArrowUp size={13} /></button
					>
					<button
						type="button"
						class={iconBtn}
						aria-label="Move {c.name} down"
						disabled={i === chosen.length - 1}
						onclick={() => move(i, 1)}><ArrowDown size={13} /></button
					>
					<button
						type="button"
						class={iconBtn}
						aria-label="Remove {c.name}"
						onclick={() => (draft = draft.filter((id) => id !== c.id))}><X size={13} /></button
					>
				</li>
			{/each}
		</ul>
	{:else}
		<p class="mt-1.5 text-sm text-faint">None yet — add some below.</p>
	{/if}

	<div class="mt-4 flex items-center gap-3">
		<p class="text-xs text-muted">Add</p>
		<Input bind:value={search} placeholder="Search commands…" class="ml-auto h-7 w-48 text-xs" />
	</div>
	<ul class="mt-1.5 max-h-64 divide-y divide-border overflow-y-auto border border-border">
		{#each others as c (c.id)}
			{@const Icon = providerIcon(c.provider_icon)}
			<li>
				<button
					type="button"
					class="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-sm hover:bg-surface-2"
					onclick={() => (draft = [...draft, c.id])}
				>
					<Icon size={13} class="shrink-0 text-muted" />
					<span class="min-w-0 flex-1 truncate">{c.name}</span>
					<span class="text-xs text-faint">{c.provider_label}</span>
					<Plus size={13} class="shrink-0 text-muted" />
				</button>
			</li>
		{:else}
			<li class="px-2.5 py-2 text-sm text-faint">
				{commands.length ? 'No other commands match.' : 'No commands yet.'}
			</li>
		{/each}
	</ul>

	{#snippet footer()}
		<Button onclick={() => (open = false)}>Cancel</Button>
		<Button
			variant="primary"
			onclick={() => {
				onsave(draft);
				open = false;
			}}>Save</Button
		>
	{/snippet}
</Dialog>
