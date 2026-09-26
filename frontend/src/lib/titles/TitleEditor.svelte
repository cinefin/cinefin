<script lang="ts">
	// The title-card editing surface: a 1920×1080 canvas of posters, text, images and shapes.
	import type { Snippet } from 'svelte';
	import { beforeNavigate } from '$app/navigation';
	import {
		ArrowDown,
		ArrowUp,
		Clock,
		Copy,
		Expand,
		FileImage,
		Image,
		Layers,
		Save,
		Square,
		Trash2,
		Type,
		Wand2,
		ZoomIn,
		ZoomOut
	} from '@lucide/svelte';
	import { onDestroy } from 'svelte';
	import { api, toApiError, unwrap, type ApiError } from '$lib/api/client';
	import type { components } from '$lib/api/types.gen';
	import { showToast } from '$lib/toast.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import ElementsList from '$lib/titles/ElementsList.svelte';
	import PropertiesPanel from '$lib/titles/PropertiesPanel.svelte';
	import {
		emptyTemplateConfig,
		TitleCanvasEditor,
		type TTFeature,
		type TTTemplateConfig
	} from '$lib/titles/canvas';

	type TitleTemplate = components['schemas']['TitleTemplateSchema'];
	type ProgrammeListItem = components['schemas']['ProgrammeListItemSchema'];
	type MovieDetail = components['schemas']['MovieDetailSchema'];

	interface Props {
		/** null = a template that does not exist yet (save POSTs it). */
		templateId: number | null;
		/** Mirrors the unsaved state out, for the host's own guards. */
		dirty?: boolean;
		/** After a successful save — the host refreshes what it shows. */
		onsaved?: (templateId: number) => void;
		/** Host actions for the toolbar's right-hand end (Done, …). */
		actions?: Snippet;
	}

	let {
		templateId: initialTemplateId,
		dirty: dirtyOut = $bindable(false),
		onsaved,
		actions
	}: Props = $props();

	// The canvas engine mutates element objects in place; `tick` is bumped on
	// every change and the panels take fresh snapshots per tick.
	let tick = $state(0);
	let stageEl = $state<HTMLDivElement | null>(null);
	let containerEl = $state<HTMLDivElement | null>(null);
	let editor = $state<TitleCanvasEditor | null>(null);

	let ctxMenu = $state<{ x: number; y: number; hit: number; single: boolean } | null>(null);

	const host = {
		onChange: () => {
			tick++;
		},
		onEdited: () => hideServerPreview(),
		onContextMenu: (clientX: number, clientY: number, hit: number) => {
			ctxMenu = {
				x: Math.min(clientX, window.innerWidth - 190),
				y: Math.min(clientY, window.innerHeight - 170),
				hit,
				single: (editor?.selectedIndices.length ?? 0) === 1
			};
		}
	};

	// Template metadata (outside the canvas engine).
	let templateId = $state<number | null>(null);
	let name = $state('');
	let description = $state('');
	let defaultDuration = $state(10);
	let metaDirty = $state(false);

	let loading = $state(true);
	let loadError = $state<ApiError | null>(null);
	let initialConfig: TTTemplateConfig = emptyTemplateConfig();

	async function loadTemplate(rid: string) {
		loading = true;
		loadError = null;
		// Drop the stale engine so it reattaches to the fresh canvas element.
		editor?.destroy();
		editor = null;
		try {
			if (rid === 'new') {
				templateId = null;
				name = '';
				description = '';
				defaultDuration = 10;
				metaDirty = false;
				initialConfig = emptyTemplateConfig();
			} else {
				// Bare-object endpoint (no envelope) — read res.data directly.
				const res = await api.GET('/api/v2/titlegen/templates/{template_id}', {
					params: { path: { template_id: Number(rid) } }
				});
				if (!res.data) throw toApiError(undefined, res.response);
				const t = res.data as TitleTemplate;
				templateId = t.id;
				name = t.name;
				description = t.description;
				defaultDuration = t.default_duration;
				metaDirty = false;
				const cfg = t.template_config as Partial<TTTemplateConfig>;
				initialConfig = {
					canvas: cfg.canvas ?? { width: 1920, height: 1080 },
					elements: cfg.elements ?? []
				};
			}
			loading = false;
		} catch (e) {
			loadError = toApiError(e);
			loading = false;
		}
	}

	// One load only; the host remounts this component when it needs a different template.
	let booted = false;
	$effect(() => {
		if (booted) return;
		booted = true;
		void loadTemplate(initialTemplateId === null ? 'new' : String(initialTemplateId));
	});

	// Create the engine once the canvas is in the DOM (after load resolves).
	$effect(() => {
		if (!stageEl || editor) return;
		const ed = new TitleCanvasEditor(stageEl, host);
		editor = ed;
		ed.loadConfig(initialConfig);
		ed.calculateOptimalZoom(containerEl?.clientWidth ?? 840);
		ed.render();
		// Konva paints text to a canvas, which never triggers @font-face loading, so
		// document.fonts.ready would resolve with the bundled faces still absent.
		// Request each family explicitly, then re-render with the real metrics.
		void loadTitleFonts().then(() => ed.render());
	});

	onDestroy(() => {
		editor?.destroy();
		hideServerPreview();
	});

	/** See ProgrammeEditor: the host's discard dialog calls this first, so the
	 *  navigation guard below does not ask the same question twice. */
	export function discardChanges(): void {
		if (editor) editor.isDirty = false;
		metaDirty = false;
		tick++;
	}

	const elementCount = $derived.by(() => {
		void tick;
		return editor?.config.elements.length ?? 0;
	});
	const zoomPercent = $derived.by(() => {
		void tick;
		return Math.round((editor?.zoom ?? 0.4) * 100);
	});
	$effect(() => {
		dirtyOut = dirty;
	});

	const dirty = $derived.by(() => {
		void tick;
		return (editor?.isDirty ?? false) || metaDirty;
	});
	const canSave = $derived(name.trim().length > 0 && elementCount > 0);

	function onBeforeUnload(e: BeforeUnloadEvent) {
		if (dirty) {
			e.preventDefault();
			e.returnValue = '';
		}
	}
	beforeNavigate((nav) => {
		if (dirty && !window.confirm('Leave the editor? Unsaved changes will be lost.')) {
			nav.cancel();
		}
	});

	function onKeyDown(e: KeyboardEvent) {
		// Don't hijack typing in form fields
		const target = e.target as HTMLElement;
		const tag = (target.tagName || '').toLowerCase();
		if (tag === 'input' || tag === 'select' || tag === 'textarea' || target.isContentEditable)
			return;
		editor?.handleKeyDown(e);
	}

	let saving = $state(false);

	async function saveTemplate() {
		if (!editor) return;
		const trimmed = name.trim();
		if (!trimmed) {
			showToast('Please enter a template name', 'warning');
			return;
		}
		if (editor.config.elements.length === 0) {
			showToast('Please add at least one element', 'warning');
			return;
		}

		const payload = {
			name: trimmed,
			description,
			default_duration: defaultDuration,
			template_config: editor.config as unknown as Record<string, never>
		};

		saving = true;
		try {
			let saved: TitleTemplate;
			if (templateId) {
				const res = await api.PUT('/api/v2/titlegen/templates/{template_id}', {
					params: { path: { template_id: templateId } },
					body: payload
				});
				if (res.error !== undefined || !res.data) throw toApiError(res.error, res.response);
				saved = res.data as TitleTemplate;
			} else {
				const res = await api.POST('/api/v2/titlegen/templates', { body: payload });
				if (res.error !== undefined || !res.data) throw toApiError(res.error, res.response);
				saved = res.data as TitleTemplate;
			}
			editor.isDirty = false;
			metaDirty = false;
			tick++;
			showToast('Template saved successfully!', 'success');
			const created = templateId === null;
			templateId = saved.id;
			if (created) onsaved?.(saved.id);
		} catch (e) {
			console.error('Failed to save template:', e);
			showToast(e instanceof Error ? e.message : 'Failed to save template', 'error');
		} finally {
			saving = false;
		}
	}

	// Live preview against a real programme (supplementary — a failure just leaves the placeholder).
	let programmes = $state<ProgrammeListItem[]>([]);
	$effect(() => {
		void (async () => {
			try {
				const data = await unwrap(api.GET('/api/v2/programmes/list'));
				programmes = data?.programmes ?? [];
			} catch (e) {
				console.error('Failed to load programmes for preview:', e);
			}
		})();
	});

	let previewProgrammeId = $state('');

	/** Minimal shape of a programme rundown row (details is an untyped dict
	 * in the backend schema; movie rows carry movie_id — see
	 * ninja_views/programmes/management.py get_programme_detail). */
	interface RundownItem {
		type: string;
		title?: string | null;
		details?: { movie_id?: number | null } | null;
	}

	async function loadPreviewProgramme(id: string) {
		previewProgrammeId = id;
		hideServerPreview();
		if (!editor) return;
		if (!id) {
			editor.setPreviewData(null);
			return;
		}
		try {
			const data = await unwrap(
				api.GET('/api/v2/programmes/{programme_id}', {
					params: { path: { programme_id: Number(id) } }
				})
			);
			const programme = data.programme;
			const movieItems = ((programme.items ?? []) as unknown as RundownItem[]).filter(
				(it) => it.type === 'movie' && it.details?.movie_id
			);

			const features: TTFeature[] = await Promise.all(
				movieItems.map(async (it) => {
					try {
						const m: MovieDetail = await unwrap(
							api.GET('/api/v2/movies/{movie_id}', {
								params: { path: { movie_id: it.details!.movie_id! } }
							})
						);
						return {
							title: m.title || it.title || '',
							director: m.director || '',
							year: m.year != null ? String(m.year) : '',
							certification: m.certification || '',
							runtime: m.runtime != null ? `${m.runtime} min` : '',
							poster: m.thumbnail_url || ''
						};
					} catch {
						return {
							title: it.title || '',
							director: '',
							year: '',
							certification: '',
							runtime: '',
							poster: ''
						};
					}
				})
			);

			editor.setPreviewData({ programme_name: programme.name || '', features });
		} catch (e) {
			console.error('Failed to load preview programme:', e);
			showToast('Failed to load preview data', 'error');
		}
	}

	let serverPreviewUrl = $state<string | null>(null);
	let serverPreviewBusy = $state(false);

	async function toggleServerPreview() {
		if (!editor) return;
		if (serverPreviewUrl) {
			hideServerPreview();
			return;
		}
		serverPreviewBusy = true;
		try {
			const res = await api.POST('/api/v2/titlegen/preview', {
				body: {
					template_config: editor.config as unknown as Record<string, never>,
					programme_id: previewProgrammeId ? Number(previewProgrammeId) : null
				},
				parseAs: 'blob'
			});
			if (!res.response.ok || res.data === undefined) {
				throw new Error(`render failed (${res.response.status})`);
			}
			serverPreviewUrl = URL.createObjectURL(res.data as unknown as Blob);
		} catch (e) {
			console.error('Server preview failed:', e);
			showToast('Could not render the server preview', 'error');
		} finally {
			serverPreviewBusy = false;
		}
	}

	function hideServerPreview() {
		if (!serverPreviewUrl) return;
		URL.revokeObjectURL(serverPreviewUrl);
		serverPreviewUrl = null;
	}

	function ctxAction(fn: () => void) {
		fn();
		ctxMenu = null;
	}

	// The bundled title-card faces (the @font-face set below / PIL's BUNDLED_FONTS).
	const TITLE_FONTS = ['Bebas Neue', 'Courier Prime', 'Inter', 'Oswald', 'Playfair Display'];
	function loadTitleFonts(): Promise<unknown> {
		if (typeof document === 'undefined' || !('fonts' in document)) return Promise.resolve();
		return Promise.allSettled(TITLE_FONTS.map((f) => document.fonts.load(`48px "${f}"`)));
	}

	const addButtons = [
		{ type: 'poster', label: 'Movie poster', icon: Image },
		{ type: 'text', label: 'Text label', icon: Type },
		{ type: 'rectangle', label: 'Rectangle', icon: Square },
		{ type: 'image', label: 'Custom image', icon: FileImage }
	];

	const fieldCls =
		'h-9 w-full rounded-md border border-border-strong bg-surface-2 px-2.5 text-sm text-text ' +
		'placeholder:text-faint focus:border-accent-dim';
	const labelCls = 'flex flex-col gap-1 text-xs text-muted';
	const menuBtn =
		'flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm text-text hover:bg-surface-3';
</script>

<svelte:window
	onbeforeunload={onBeforeUnload}
	onkeydown={onKeyDown}
	onresize={() => {
		if (editor && containerEl) {
			editor.calculateOptimalZoom(containerEl.clientWidth);
			editor.render();
		}
	}}
/>
<svelte:document onclick={() => (ctxMenu = null)} onscrollcapture={() => (ctxMenu = null)} />

<div class="mb-4 flex flex-wrap items-center gap-2">
	<span class="mr-auto flex items-center gap-4 font-mono text-xs text-muted">
		<span class="inline-flex items-center gap-1.5"
			><Layers size={12} /> {elementCount} elements</span
		>
		<span class="inline-flex items-center gap-1.5"><Clock size={12} /> {defaultDuration}s</span>
	</span>

	{#if dirty}
		<span class="font-mono text-xs text-warning">unsaved changes</span>
	{/if}
	<Button variant="primary" disabled={!canSave || saving} onclick={() => void saveTemplate()}>
		<Save size={14} />
		{saving ? 'Saving…' : 'Save template'}
	</Button>
	{#if actions}{@render actions()}{/if}
</div>

{#if loading}
	<Spinner label="Loading template…" />
{:else if loadError}
	<ErrorState
		error={loadError}
		retry={() => void loadTemplate(initialTemplateId === null ? 'new' : String(initialTemplateId))}
	/>
{:else}
	<div class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
		<div class="min-w-0 space-y-4">
			<Card title="Canvas preview">
				{#snippet actions()}
					<label
						class="flex items-center gap-1.5 text-xs text-muted"
						title="Fill the canvas with a real programme's data to check the layout"
					>
						Preview with
						<Select
							value={previewProgrammeId}
							onchange={(e) => void loadPreviewProgramme((e.target as HTMLSelectElement).value)}
						>
							<option value="">Placeholders (design view)</option>
							{#each programmes as p (p.id)}
								<option value={String(p.id)}>{p.name}</option>
							{/each}
						</Select>
					</label>
					<Button
						size="sm"
						variant={serverPreviewUrl ? 'primary' : 'default'}
						disabled={serverPreviewBusy}
						title="Render this layout with the exact server-side generator - the ground truth for fonts and text wrapping"
						onclick={() => void toggleServerPreview()}
					>
						<Wand2 size={13} /> Render
					</Button>
					<Button size="sm" title="Zoom out" onclick={() => editor?.changeZoom(-0.1)}>
						<ZoomOut size={13} />
					</Button>
					<Button
						size="sm"
						title="Fit to screen"
						onclick={() => {
							if (editor && containerEl) {
								editor.calculateOptimalZoom(containerEl.clientWidth);
								editor.render();
							}
						}}
					>
						<Expand size={13} />
					</Button>
					<span class="w-10 text-center font-mono text-xs text-muted">{zoomPercent}%</span>
					<Button size="sm" title="Zoom in" onclick={() => editor?.changeZoom(0.1)}>
						<ZoomIn size={13} />
					</Button>
				{/snippet}

				<div bind:this={containerEl} class="overflow-auto bg-bg p-2 text-center">
					<div class="relative inline-block border border-border">
						<div bind:this={stageEl} class="block bg-black"></div>
						{#if serverPreviewUrl}
							<img
								src={serverPreviewUrl}
								alt="Server-rendered preview"
								class="absolute inset-0 z-[5] h-full w-full outline-2 outline-accent"
							/>
						{/if}
					</div>
				</div>
			</Card>

			<Card title="Template settings">
				<div class="grid gap-3 sm:grid-cols-[2fr_2fr_1fr]">
					<label class={labelCls}>
						Template name *
						<input
							type="text"
							class={fieldCls}
							placeholder="e.g. Double feature"
							bind:value={name}
							oninput={() => (metaDirty = true)}
						/>
					</label>
					<label class={labelCls}>
						Description
						<input
							type="text"
							class={fieldCls}
							placeholder="Optional description"
							bind:value={description}
							oninput={() => (metaDirty = true)}
						/>
					</label>
					<label class={labelCls}>
						Default duration (s)
						<input
							type="number"
							class={fieldCls}
							min="1"
							max="300"
							value={defaultDuration}
							onchange={(e) => {
								defaultDuration = parseInt((e.target as HTMLInputElement).value) || 10;
								metaDirty = true;
							}}
						/>
					</label>
				</div>
			</Card>
		</div>

		<div class="space-y-4">
			<Card title="Add element">
				<div class="grid grid-cols-2 gap-2">
					{#each addButtons as b (b.type)}
						<Button size="sm" onclick={() => editor?.addElement(b.type)}>
							<b.icon size={13} />
							{b.label}
						</Button>
					{/each}
				</div>
			</Card>

			<Card title="Elements" class="[&>div]:p-0">
				{#if editor}
					<ElementsList {editor} {tick} />
				{/if}
			</Card>

			<Card title="Properties">
				{#if editor}
					<PropertiesPanel {editor} {tick} />
				{/if}
			</Card>
		</div>
	</div>
{/if}

{#if ctxMenu && editor}
	{@const menu = ctxMenu}
	{@const ed = editor}
	<div
		class="fixed z-50 w-44 rounded-md border border-border-strong bg-surface-2 py-1"
		style="left: {menu.x}px; top: {menu.y}px"
		role="menu"
		tabindex="-1"
		onclick={(e) => e.stopPropagation()}
		onkeydown={(e) => {
			if (e.key === 'Escape') ctxMenu = null;
		}}
	>
		<button type="button" class={menuBtn} onclick={() => ctxAction(() => ed.duplicateSelected())}>
			<Copy size={13} /> Duplicate
		</button>
		{#if menu.single}
			<button
				type="button"
				class={menuBtn}
				onclick={() => ctxAction(() => ed.moveElement(menu.hit, 1))}
			>
				<ArrowUp size={13} /> Bring forward
			</button>
			<button
				type="button"
				class={menuBtn}
				onclick={() => ctxAction(() => ed.moveElement(menu.hit, -1))}
			>
				<ArrowDown size={13} /> Send backward
			</button>
		{/if}
		<hr class="my-1 border-border" />
		<button
			type="button"
			class="{menuBtn} text-danger hover:text-danger"
			onclick={() => ctxAction(() => ed.deleteSelected())}
		>
			<Trash2 size={13} /> Delete
		</button>
	</div>
{/if}

<style>
	/* Bundled title-card fonts — the SAME files PIL renders with, so the
	   canvas preview is true WYSIWYG (served by Django from static/fonts). */
	@font-face {
		font-family: 'Bebas Neue';
		src: url('/static/fonts/BebasNeue.ttf');
	}
	@font-face {
		font-family: 'Courier Prime';
		src: url('/static/fonts/CourierPrime.ttf');
	}
	@font-face {
		font-family: 'Inter';
		src: url('/static/fonts/Inter.ttf');
	}
	@font-face {
		font-family: 'Oswald';
		src: url('/static/fonts/Oswald.ttf');
	}
	@font-face {
		font-family: 'Playfair Display';
		src: url('/static/fonts/PlayfairDisplay.ttf');
	}
</style>
