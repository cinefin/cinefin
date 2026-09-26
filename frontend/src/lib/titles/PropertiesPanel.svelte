<script lang="ts">
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
		Trash2,
		Upload,
		X
	} from '@lucide/svelte';
	import { api } from '$lib/api/client';
	import { showToast } from '$lib/toast.svelte';
	import { uploadWithProgress } from '$lib/upload';
	import Button from '$lib/components/ui/Button.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import FontPicker, { type FontOption } from './FontPicker.svelte';
	import type { TitleCanvasEditor, TTAlignMode, TTElement } from './canvas';

	interface Props {
		editor: TitleCanvasEditor;
		/** Bumped by the page on every editor change — forces a re-read. */
		tick: number;
	}

	let { editor, tick }: Props = $props();

	// Fresh snapshots per tick: the editor mutates element objects in place.
	const count = $derived.by(() => {
		void tick;
		return editor.selectedIndices.length;
	});
	const sel = $derived.by<TTElement | null>(() => {
		void tick;
		const el = editor.selectedElement;
		return el ? { ...el } : null;
	});
	const alignAreaMode = $derived.by(() => {
		void tick;
		return editor.alignAreaMode;
	});
	const canDistribute = $derived(alignAreaMode === 'canvas' ? count >= 2 : count >= 3);

	// Seeded with the bundled set until the API fetch lands.
	let fonts = $state<FontOption[]>([
		{ name: 'Bebas Neue', bundled: true },
		{ name: 'Courier Prime', bundled: true },
		{ name: 'Inter', bundled: true },
		{ name: 'Oswald', bundled: true },
		{ name: 'Playfair Display', bundled: true }
	]);
	$effect(() => {
		void (async () => {
			try {
				const res = await api.GET('/api/v2/titlegen/fonts');
				if (Array.isArray(res.data) && res.data.length) fonts = res.data;
			} catch (e) {
				console.warn('Could not load font list; offering bundled fonts only', e);
			}
		})();
	});

	let availableImages = $state<string[]>([]);
	let imagesLoaded = false;
	$effect(() => {
		if (sel?.type !== 'image' || imagesLoaded) return;
		imagesLoaded = true;
		void loadAvailableImages();
	});

	async function loadAvailableImages() {
		try {
			const res = await api.GET('/api/v2/titlegen/images');
			availableImages = res.data ?? [];
		} catch (e) {
			console.error('Failed to load available images:', e);
		}
	}

	let fileInput: HTMLInputElement | undefined = $state();

	async function uploadImage(file: File | undefined) {
		if (!file) return;

		if (!file.type.match(/image\/(png|jpeg)/)) {
			showToast('Please select a PNG or JPEG image', 'error');
			return;
		}

		try {
			// Bare response, no data envelope: { success, message, url, filename }.
			const result = await uploadWithProgress<{ success: boolean; message: string; url?: string }>(
				'/api/v2/titlegen/upload-image',
				file
			);
			if (result.success && result.url) {
				set('path', result.url);
				showToast('Image uploaded successfully!', 'success');
				await loadAvailableImages();
			} else {
				showToast(result.message || 'Failed to upload image', 'error');
			}
		} catch (e) {
			console.error('Failed to upload image:', e);
			showToast(e instanceof Error ? e.message : 'Failed to upload image', 'error');
		}
	}

	function set(property: string, value: unknown) {
		editor.updateElementProperty(property, value);
	}

	/** Selects can't take onfocus through the primitive — snapshot at change time instead. */
	function snapSet(property: string, value: unknown) {
		editor.snapshot();
		editor.updateElementProperty(property, value);
	}

	function onFieldFocus() {
		editor.snapshot();
	}

	function inputValue(e: Event): string {
		return (e.target as HTMLInputElement).value;
	}

	const field =
		'h-9 w-full rounded-md border border-border-strong bg-surface-2 px-2.5 text-sm text-text ' +
		'placeholder:text-faint focus:border-accent-dim';
	const label = 'flex flex-col gap-1 text-xs text-muted';
	const alignBtn =
		'inline-flex h-8 items-center justify-center rounded-md border border-border-strong ' +
		'bg-surface-2 text-muted hover:bg-surface-3 hover:text-text';

	const aligns: Array<{ mode: TTAlignMode; title: string; icon: typeof AlignLeft }> = [
		{ mode: 'left', title: 'Align left edges', icon: AlignLeft },
		{ mode: 'centerH', title: 'Align horizontal centers', icon: AlignCenter },
		{ mode: 'right', title: 'Align right edges', icon: AlignRight },
		{ mode: 'top', title: 'Align top edges', icon: ArrowUp },
		{ mode: 'middle', title: 'Align vertical centers', icon: MoveVertical },
		{ mode: 'bottom', title: 'Align bottom edges', icon: ArrowDown }
	];
</script>

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
			Distribute centers
			<div class="flex gap-2">
				<Button
					size="sm"
					class="flex-1"
					disabled={!canDistribute}
					onclick={() => editor.distribute('h', 'centers')}
				>
					<MoveHorizontal size={13} /> Horizontal
				</Button>
				<Button
					size="sm"
					class="flex-1"
					disabled={!canDistribute}
					onclick={() => editor.distribute('v', 'centers')}
				>
					<MoveVertical size={13} /> Vertical
				</Button>
			</div>
		</div>

		<div class={label}>
			Distribute gaps (equal spacing)
			<div class="flex gap-2">
				<Button
					size="sm"
					class="flex-1"
					disabled={!canDistribute}
					onclick={() => editor.distribute('h', 'gaps')}
				>
					<MoveHorizontal size={13} /> Horizontal
				</Button>
				<Button
					size="sm"
					class="flex-1"
					disabled={!canDistribute}
					onclick={() => editor.distribute('v', 'gaps')}
				>
					<MoveVertical size={13} /> Vertical
				</Button>
			</div>
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
			<label class={label}>
				X position
				<input
					type="number"
					class={field}
					value={sel.x}
					onfocus={onFieldFocus}
					onchange={(e) => set('x', inputValue(e))}
				/>
			</label>
			<label class={label}>
				Y position
				<input
					type="number"
					class={field}
					value={sel.y}
					onfocus={onFieldFocus}
					onchange={(e) => set('y', inputValue(e))}
				/>
			</label>
		</div>

		<div class={label}>
			Alignment
			<div class="flex gap-2">
				<Button
					size="sm"
					class="flex-1"
					title="Center horizontally on canvas"
					onclick={() => editor.centerElementHorizontally()}
				>
					<MoveHorizontal size={13} /> Center H
				</Button>
				<Button
					size="sm"
					class="flex-1"
					title="Center vertically on canvas"
					onclick={() => editor.centerElementVertically()}
				>
					<MoveVertical size={13} /> Center V
				</Button>
			</div>
		</div>

		{#if sel.type !== 'text'}
			<div class="flex items-end gap-2">
				<label class="{label} flex-1">
					Width
					<input
						type="number"
						class={field}
						value={sel.width}
						onfocus={onFieldFocus}
						onchange={(e) => set('width', inputValue(e))}
					/>
				</label>
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
				<label class="{label} flex-1">
					Height
					<input
						type="number"
						class={field}
						value={sel.height}
						onfocus={onFieldFocus}
						onchange={(e) => set('height', inputValue(e))}
					/>
				</label>
			</div>
		{/if}

		{#if sel.type === 'poster'}
			<label class={label}>
				Feature index
				<input
					type="number"
					class={field}
					min="0"
					max="4"
					value={sel.feature_index || 0}
					onfocus={onFieldFocus}
					onchange={(e) => set('feature_index', inputValue(e))}
				/>
				<span class="text-faint">Which movie poster to show (0 = first feature)</span>
			</label>
		{:else if sel.type === 'text'}
			<label class={label}>
				Text field
				<Select
					value={sel.field || 'title'}
					onchange={(e) => snapSet('field', (e.target as HTMLSelectElement).value)}
				>
					<option value="title">Movie title</option>
					<option value="director">Director</option>
					<option value="year">Year</option>
					<option value="certification">Certification</option>
					<option value="runtime">Runtime</option>
					<option value="programme_name">Programme name</option>
				</Select>
			</label>
			<label class={label}>
				Feature index
				<input
					type="number"
					class={field}
					min="0"
					max="4"
					value={sel.feature_index || 0}
					onfocus={onFieldFocus}
					onchange={(e) => set('feature_index', inputValue(e))}
				/>
				<span class="text-faint">Which movie to show data from (0 = first feature)</span>
			</label>
			<div class={label}>
				Font
				<FontPicker {fonts} value={sel.font || 'Inter'} onpick={(f) => set('font', f)} />
			</div>
			<label class={label}>
				Font size
				<input
					type="number"
					class={field}
					value={sel.size || 48}
					onfocus={onFieldFocus}
					onchange={(e) => set('size', inputValue(e))}
				/>
			</label>
			<label class={label}>
				Max width (wrap)
				<input
					type="number"
					class={field}
					min="20"
					placeholder="No wrap"
					value={sel.max_width ?? ''}
					onfocus={onFieldFocus}
					onchange={(e) => set('max_width', inputValue(e))}
				/>
				<span class="text-faint">Blank = single line; set a width to wrap long text</span>
			</label>
			<label class={label}>
				Alignment
				<Select
					value={sel.align || 'left'}
					onchange={(e) => snapSet('align', (e.target as HTMLSelectElement).value)}
				>
					<option value="left">Left</option>
					<option value="center">Center</option>
					<option value="right">Right</option>
				</Select>
			</label>
			<label class={label}>
				Color
				<div class="flex items-center gap-2">
					<input
						type="color"
						class="h-9 w-12 shrink-0 rounded-md border border-border-strong bg-surface-2 px-1"
						value={sel.color || '#FFFFFF'}
						onfocus={onFieldFocus}
						onchange={(e) => set('color', inputValue(e))}
					/>
					<input
						type="text"
						class={field}
						value={sel.color || '#FFFFFF'}
						onfocus={onFieldFocus}
						onchange={(e) => set('color', inputValue(e))}
					/>
				</div>
			</label>
		{:else if sel.type === 'rectangle'}
			<label class={label}>
				Color
				<div class="flex items-center gap-2">
					<input
						type="color"
						class="h-9 w-12 shrink-0 rounded-md border border-border-strong bg-surface-2 px-1"
						value={sel.color || '#FFFFFF'}
						onfocus={onFieldFocus}
						onchange={(e) => set('color', inputValue(e))}
					/>
					<input
						type="text"
						class={field}
						value={sel.color || '#FFFFFF'}
						onfocus={onFieldFocus}
						onchange={(e) => set('color', inputValue(e))}
					/>
				</div>
			</label>
			<label class={label}>
				Fill style
				<Select
					value={sel.fill ? 'true' : 'false'}
					onchange={(e) => snapSet('fill', (e.target as HTMLSelectElement).value)}
				>
					<option value="true">Filled</option>
					<option value="false">Outline</option>
				</Select>
			</label>
		{:else if sel.type === 'image'}
			<div class={label}>
				Image
				<div class="flex gap-2">
					<input
						type="file"
						accept="image/png,image/jpeg"
						class="hidden"
						bind:this={fileInput}
						onchange={(e) => {
							const input = e.target as HTMLInputElement;
							void uploadImage(input.files?.[0]);
							input.value = '';
						}}
					/>
					<Button size="sm" variant="primary" onclick={() => fileInput?.click()}>
						<Upload size={13} /> Upload new
					</Button>
					{#if sel.path}
						<Button size="sm" variant="danger" onclick={() => set('path', '')}>
							<X size={13} /> Clear
						</Button>
					{/if}
				</div>
				<Select
					value={availableImages.includes(sel.path || '') ? sel.path : ''}
					onchange={(e) => {
						const url = (e.target as HTMLSelectElement).value;
						if (url) set('path', url);
					}}
				>
					<option value="">-- Select from uploaded images --</option>
					{#each availableImages as url (url)}
						<option value={url}>{url.split('/').pop()}</option>
					{/each}
				</Select>
				<input
					type="text"
					class={field}
					placeholder="No image selected"
					value={sel.path || ''}
					onfocus={onFieldFocus}
					onchange={(e) => set('path', inputValue(e))}
				/>
				<span class="text-faint">Upload or select a PNG or JPEG image</span>
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
