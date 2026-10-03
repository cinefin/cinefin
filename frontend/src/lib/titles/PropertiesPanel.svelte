<script lang="ts">
	import ImageLibrary from '$lib/components/ImageLibrary.svelte';
	import {
		AlignCenter,
		AlignLeft,
		AlignRight,
		ArrowDown,
		ArrowUp,
		Copy,
		Lock,
		LockOpen,
		MousePointer,
		MoveHorizontal,
		MoveVertical,
		Trash2
	} from '@lucide/svelte';
	import type { HTMLInputAttributes } from 'svelte/elements';
	import { api } from '$lib/api/client';
	import Button from '$lib/components/ui/Button.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import FontPicker, { type FontOption } from './FontPicker.svelte';
	import { TITLE_FONTS, type TitleCanvasEditor, type TTAlignMode, type TTElement } from './canvas';

	interface Props {
		editor: TitleCanvasEditor;
		/** Bumped by the page on every editor change — forces a re-read. */
		tick: number;
	}

	let { editor, tick }: Props = $props();

	// Fresh snapshots per tick: the editor mutates element objects in place.
	// `tick >= 0` is always true; reading it re-derives on every editor change.
	const count = $derived(tick >= 0 ? editor.selectedIndices.length : 0);
	const sel = $derived.by<TTElement | null>(() => {
		void tick;
		const el = editor.selectedElement;
		return el ? { ...el } : null;
	});
	const alignAreaMode = $derived(tick >= 0 ? editor.alignAreaMode : 'selection');
	const canDistribute = $derived(alignAreaMode === 'canvas' ? count >= 2 : count >= 3);

	// Seeded with the bundled set until the API fetch lands.
	let fonts = $state<FontOption[]>(
		Object.keys(TITLE_FONTS).map((name) => ({ name, bundled: true }))
	);
	api.GET('/api/v2/titlegen/fonts').then(
		(res) => {
			if (Array.isArray(res.data) && res.data.length) fonts = res.data;
		},
		(e) => console.warn('Could not load font list; offering bundled fonts only', e)
	);

	const set = (property: string, value: unknown) => editor.updateElementProperty(property, value);

	/** Selects can't take onfocus through the primitive — snapshot at change time instead. */
	function snapSet(property: string, e: Event) {
		editor.snapshot();
		set(property, (e.target as HTMLSelectElement).value);
	}

	const onFieldFocus = () => editor.snapshot();
	const inputValue = (e: Event) => (e.target as HTMLInputElement).value;

	const field =
		'h-9 w-full rounded-md border border-border-strong bg-surface-2 px-2.5 text-sm text-text ' +
		'placeholder:text-faint focus:border-accent-dim';
	const label = 'flex flex-col gap-1 text-xs text-muted';
	const alignBtn =
		'inline-flex h-8 items-center justify-center rounded-md border border-border-strong ' +
		'bg-surface-2 text-muted hover:bg-surface-3 hover:text-text';

	type PairButton = {
		icon: typeof AlignLeft;
		text: string;
		title?: string;
		disabled?: boolean;
		onclick: () => void;
	};

	const aligns: Array<{ mode: TTAlignMode; title: string; icon: typeof AlignLeft }> = [
		{ mode: 'left', title: 'Align left edges', icon: AlignLeft },
		{ mode: 'centerH', title: 'Align horizontal centers', icon: AlignCenter },
		{ mode: 'right', title: 'Align right edges', icon: AlignRight },
		{ mode: 'top', title: 'Align top edges', icon: ArrowUp },
		{ mode: 'middle', title: 'Align vertical centers', icon: MoveVertical },
		{ mode: 'bottom', title: 'Align bottom edges', icon: ArrowDown }
	];
</script>

{#snippet num(
	text: string,
	prop: string,
	value: number | string | undefined | null,
	hint = '',
	attrs: HTMLInputAttributes = {},
	cls = label
)}
	<label class={cls}>
		{text}
		<input
			type="number"
			class={field}
			{...attrs}
			{value}
			onfocus={onFieldFocus}
			onchange={(e) => set(prop, inputValue(e))}
		/>
		{#if hint}<span class="text-faint">{hint}</span>{/if}
	</label>
{/snippet}

{#snippet choice(text: string, prop: string, value: string, options: [string, string][])}
	<label class={label}>
		{text}
		<Select {value} onchange={(e) => snapSet(prop, e)}>
			{#each options as [v, l] (v)}
				<option value={v}>{l}</option>
			{/each}
		</Select>
	</label>
{/snippet}

{#snippet color(value: string)}
	<label class={label}>
		Color
		<div class="flex items-center gap-2">
			<input
				type="color"
				class="h-9 w-12 shrink-0 rounded-md border border-border-strong bg-surface-2 px-1"
				{value}
				onfocus={onFieldFocus}
				onchange={(e) => set('color', inputValue(e))}
			/>
			<input
				type="text"
				class={field}
				{value}
				onfocus={onFieldFocus}
				onchange={(e) => set('color', inputValue(e))}
			/>
		</div>
	</label>
{/snippet}

{#snippet pair(a: PairButton, b: PairButton)}
	<div class="flex gap-2">
		{#each [a, b] as x (x.text)}
			<Button size="sm" class="flex-1" title={x.title} disabled={x.disabled} onclick={x.onclick}>
				<x.icon size={13} />
				{x.text}
			</Button>
		{/each}
	</div>
{/snippet}

{#snippet distribute(heading: string, by: 'centers' | 'gaps')}
	{heading}
	{@render pair(
		{
			icon: MoveHorizontal,
			text: 'Horizontal',
			disabled: !canDistribute,
			onclick: () => editor.distribute('h', by)
		},
		{
			icon: MoveVertical,
			text: 'Vertical',
			disabled: !canDistribute,
			onclick: () => editor.distribute('v', by)
		}
	)}
{/snippet}

{#if count === 0}
	<EmptyState
		icon={MousePointer}
		title="No element selected"
		message="Select an element to edit its properties. Shift-click or drag to select several."
		compact
	/>
{:else if count > 1}
	<div class="space-y-4">
		<div class="flex items-center justify-between gap-2 text-sm text-muted">
			<span>{count} elements selected</span>
			<Button
				size="sm"
				title="Duplicate the selection (Ctrl+D)"
				onclick={() => editor.duplicateSelected()}
			>
				<Copy size={13} /> Duplicate
			</Button>
		</div>

		<label class={label}>
			Relative to
			<Select
				value={alignAreaMode}
				onchange={(e) =>
					editor.setAlignArea((e.target as HTMLSelectElement).value as 'selection' | 'canvas')}
			>
				<option value="selection">Selection bounds</option>
				<option value="canvas">Page (whole canvas)</option>
			</Select>
		</label>

		<div class={label}>
			Align
			<div class="grid grid-cols-3 gap-1.5">
				{#each aligns as a (a.mode)}
					<button
						type="button"
						class={alignBtn}
						title={a.title}
						onclick={() => editor.align(a.mode)}
					>
						<a.icon size={14} />
					</button>
				{/each}
			</div>
		</div>

		<div class={label}>
			{@render distribute('Distribute centers', 'centers')}
		</div>

		<div class={label}>
			{@render distribute('Distribute gaps (equal spacing)', 'gaps')}
			{#if !canDistribute}
				<span class="text-faint">Select 3+ (or use Page) to distribute</span>
			{/if}
		</div>

		<Button variant="danger" class="w-full" onclick={() => editor.deleteSelected()}>
			<Trash2 size={13} /> Delete selected
		</Button>
	</div>
{:else if sel}
	<div class="space-y-3">
		<label class={label}>
			Type
			<input type="text" class="{field} opacity-60" value={sel.type} disabled />
		</label>

		<div class="grid grid-cols-2 gap-2">
			{@render num('X position', 'x', sel.x)}
			{@render num('Y position', 'y', sel.y)}
		</div>

		<div class={label}>
			Alignment
			{@render pair(
				{
					icon: MoveHorizontal,
					text: 'Center H',
					title: 'Center horizontally on canvas',
					onclick: () => editor.center('x')
				},
				{
					icon: MoveVertical,
					text: 'Center V',
					title: 'Center vertically on canvas',
					onclick: () => editor.center('y')
				}
			)}
		</div>

		{#if sel.type !== 'text'}
			<div class="flex items-end gap-2">
				{@render num('Width', 'width', sel.width, '', {}, `${label} flex-1`)}
				<button
					type="button"
					class="{alignBtn} h-9 w-9 shrink-0 {sel.lock_aspect
						? 'border-accent-dim text-accent'
						: ''}"
					title={sel.lock_aspect ? 'Aspect ratio locked - unlock' : 'Lock aspect ratio'}
					onclick={() => editor.toggleAspectLock()}
				>
					{#if sel.lock_aspect}<Lock size={14} />{:else}<LockOpen size={14} />{/if}
				</button>
				{@render num('Height', 'height', sel.height, '', {}, `${label} flex-1`)}
			</div>
		{/if}

		{#if sel.type === 'poster'}
			{@render num(
				'Feature index',
				'feature_index',
				sel.feature_index || 0,
				'Which movie poster to show (0 = first feature)',
				{ min: 0, max: 4 }
			)}
		{:else if sel.type === 'text'}
			{@render choice('Text field', 'field', sel.field || 'title', [
				['title', 'Movie title'],
				['director', 'Director'],
				['year', 'Year'],
				['certification', 'Certification'],
				['runtime', 'Runtime'],
				['programme_name', 'Programme name']
			])}
			{@render num(
				'Feature index',
				'feature_index',
				sel.feature_index || 0,
				'Which movie to show data from (0 = first feature)',
				{ min: 0, max: 4 }
			)}
			<div class={label}>
				Font
				<FontPicker {fonts} value={sel.font || 'Inter'} onpick={(f) => set('font', f)} />
			</div>
			{@render num('Font size', 'size', sel.size || 48)}
			{@render num(
				'Max width (wrap)',
				'max_width',
				sel.max_width ?? '',
				'Blank = single line; set a width to wrap long text',
				{ min: 20, placeholder: 'No wrap' }
			)}
			{@render choice('Alignment', 'align', sel.align || 'left', [
				['left', 'Left'],
				['center', 'Center'],
				['right', 'Right']
			])}
			{@render color(sel.color || '#FFFFFF')}
		{:else if sel.type === 'rectangle'}
			{@render color(sel.color || '#FFFFFF')}
			{@render choice('Fill style', 'fill', sel.fill ? 'true' : 'false', [
				['true', 'Filled'],
				['false', 'Outline']
			])}
		{:else if sel.type === 'image'}
			<div class={label}>
				<span class="flex items-center">
					Image
					{#if sel.path}
						<button
							type="button"
							class="ml-auto text-xs hover:text-text"
							onclick={() => set('path', '')}
						>
							Clear
						</button>
					{/if}
				</span>
				<ImageLibrary
					library="titles"
					selected={sel.path?.split('/').pop() ?? null}
					onselect={(img) => set('path', img.url)}
				/>
			</div>
		{/if}

		<label class={label}>
			Opacity
			<div class="flex items-center gap-2">
				<input
					type="range"
					class="flex-1 accent-(--color-accent)"
					min="0"
					max="1"
					step="0.1"
					value={sel.opacity || 1.0}
					onfocus={onFieldFocus}
					oninput={(e) => set('opacity', inputValue(e))}
				/>
				<span class="w-10 text-right font-mono text-xs text-muted">
					{Math.round((sel.opacity || 1.0) * 100)}%
				</span>
			</div>
		</label>
	</div>
{/if}
