<script lang="ts">
	// The manual queue as the player holds it: the item on screen lit, reorder and remove.
	import { ArrowDown, ArrowUp, ListOrdered, X } from '@lucide/svelte';
	import { api } from '$lib/api/client';
	import { mutate } from '$lib/api/mutate';
	import { showToast } from '$lib/toast.svelte';
	import TypeBadge from '$lib/components/TypeBadge.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';

	interface Props {
		items: { title: string; kind: string }[];
		position: number | null;
		onchanged: () => void;
	}
	let { items, position, onchanged }: Props = $props();

	const BADGE: Record<string, string> = { movie: 'movie', trailer: 'trailer', media: 'bumper' };

	async function act(req: Promise<unknown>) {
		try {
			await req;
			onchanged();
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Queue change failed', 'error');
		}
	}
	const remove = (index: number) =>
		act(mutate(api.DELETE('/api/v2/playout/manual/{index}', { params: { path: { index } } })));
	const move = (index: number, to: number) =>
		act(
			mutate(
				api.POST('/api/v2/playout/manual/{index}/move', {
					params: { path: { index } },
					body: { to }
				})
			)
		);
	const iconBtn =
		'rounded-sm p-1 text-faint hover:bg-surface-3 hover:text-text disabled:pointer-events-none disabled:opacity-30';
</script>

<section class="border border-border bg-surface-1">
	<header class="flex items-center justify-between gap-3 border-b border-border px-4 py-2.5">
		<p class="inline-flex items-center gap-1.5 text-[0.8rem] font-medium text-muted">
			<ListOrdered size={13} /> Queue
		</p>
		<span class="font-mono text-xs text-muted"
			>{items.length} item{items.length === 1 ? '' : 's'}</span
		>
	</header>
	{#if !items.length}
		<EmptyState
			icon={ListOrdered}
			title="Nothing queued"
			message="Play or queue something to start. When the queue ends the ident returns."
			compact
		/>
	{:else}
		<ol>
			{#each items as item, i (i)}
				{@const current = i === position}
				<li
					class="relative flex items-center gap-2.5 border-b border-border px-3 py-2 last:border-b-0
						{current ? 'bg-surface-2' : ''} {position != null && i < position ? 'opacity-45' : ''}"
				>
					{#if current}<span class="absolute inset-y-0 left-0 w-0.5 bg-accent"></span>{/if}
					<span class="w-5 shrink-0 text-center font-mono text-xs text-faint">{i + 1}</span>
					<span class="min-w-0 flex-1">
						<span class="block truncate text-sm {current ? 'text-accent' : ''}">{item.title}</span>
						<TypeBadge
							type={BADGE[item.kind] ?? 'system'}
							short
							col
							class="mt-0.5 !text-[0.6rem]"
						/>
					</span>
					<button
						type="button"
						class={iconBtn}
						aria-label="Move up"
						disabled={i === 0}
						onclick={() => void move(i, i - 1)}><ArrowUp size={13} /></button
					>
					<button
						type="button"
						class={iconBtn}
						aria-label="Move down"
						disabled={i === items.length - 1}
						onclick={() => void move(i, i + 1)}><ArrowDown size={13} /></button
					>
					<button
						type="button"
						class={iconBtn}
						aria-label="Remove {item.title}"
						onclick={() => void remove(i)}><X size={13} /></button
					>
				</li>
			{/each}
		</ol>
	{/if}
</section>
