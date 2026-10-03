<script lang="ts">
	import { ArrowDown, ArrowUp, Copy, Layers, Trash2 } from '@lucide/svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import type { TitleCanvasEditor, TTElement } from './canvas';

	interface Props {
		editor: TitleCanvasEditor;
		/** Bumped by the page on every editor change — forces a re-read. */
		tick: number;
	}

	let { editor, tick }: Props = $props();

	// Fresh snapshots per tick (the editor mutates elements in place).
	const rows = $derived.by<Array<{ element: TTElement; title: string; selected: boolean }>>(() => {
		void tick;
		return editor.config.elements.map((element, index) => ({
			element: { ...element },
			title: editor.getElementTitle(element),
			selected: editor.selectedIndices.includes(index)
		}));
	});

	const typeColors: Record<string, string> = {
		poster: 'bg-accent-dim/40 text-accent',
		text: 'bg-success/15 text-success',
		rectangle: 'bg-warning/15 text-warning',
		image: 'bg-surface-3 text-muted'
	};
</script>

{#snippet action(Icon: typeof Copy, title: string, run: () => void, disabled = false, cls = '')}
	<button
		type="button"
		class="inline-flex h-6 w-6 items-center justify-center rounded-sm text-faint hover:bg-surface-3 hover:text-text disabled:pointer-events-none disabled:opacity-35 {cls}"
		{title}
		{disabled}
		onclick={(e) => {
			e.stopPropagation();
			run();
		}}
	>
		<Icon size={12} />
	</button>
{/snippet}

{#if rows.length === 0}
	<EmptyState
		icon={Layers}
		title="No elements yet"
		message="Add text or image elements to build the title card."
		compact
	/>
{:else}
	<ul class="divide-y divide-border">
		{#each rows as row, index (index)}
			<li>
				<div
					class="group flex w-full cursor-pointer items-center gap-2 px-2 py-2 text-left
						{row.selected ? 'bg-accent-dim/20' : 'hover:bg-surface-2'}"
					role="button"
					tabindex="0"
					onclick={(e) => editor.selectElement(index, e.shiftKey)}
					onkeydown={(e) => {
						if (e.key === 'Enter' || e.key === ' ') {
							e.preventDefault();
							editor.selectElement(index, e.shiftKey);
						}
					}}
				>
					<div class="min-w-0 flex-1">
						<div class="flex items-center gap-2">
							<span
								class="shrink-0 rounded-sm px-1.5 py-0.5 font-mono text-[10px]
									{typeColors[row.element.type] ?? 'bg-surface-3 text-muted'}"
							>
								{row.element.type}
							</span>
							<span class="truncate text-sm">{row.title}</span>
						</div>
						<p class="mt-0.5 font-mono text-[11px] text-faint">
							Position: {row.element.x}, {row.element.y} · Opacity: {Math.round(
								(row.element.opacity || 1) * 100
							)}%
						</p>
					</div>
					<div class="flex shrink-0 items-center gap-0.5">
						{@render action(Copy, 'Duplicate (Ctrl+D)', () => {
							editor.setSelection([index]);
							editor.duplicateSelected();
						})}
						{@render action(ArrowUp, 'Move up', () => editor.moveElement(index, -1), index === 0)}
						{@render action(
							ArrowDown,
							'Move down',
							() => editor.moveElement(index, 1),
							index === rows.length - 1
						)}
						{@render action(
							Trash2,
							'Delete',
							() => editor.deleteElement(index),
							false,
							'hover:text-danger'
						)}
					</div>
				</div>
			</li>
		{/each}
	</ul>
{/if}
