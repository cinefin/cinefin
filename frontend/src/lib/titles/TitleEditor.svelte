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
	import { raw } from '$lib/settings/form.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import ElementsList from '$lib/titles/ElementsList.svelte';
	import PropertiesPanel from '$lib/titles/PropertiesPanel.svelte';
	import {
		emptyTemplateConfig,
		loadTitleFonts,
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
		onChange: () => tick++,
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

	let templateId = $state<number | null>(null);
	let name = $state('');
	let description = $state('');
	let defaultDuration = $state(10);
	let metaDirty = $state(false);

	let loading = $state(true);
	let loadError = $state<ApiError | null>(null);
	let initialConfig: TTTemplateConfig = emptyTemplateConfig();

	// One template per mount; the host remounts this component for a different one.
	async function loadTemplate() {
		loading = true;
		loadError = null;
		// Drop the stale engine so it reattaches to the fresh canvas element.
		editor?.destroy();
		editor = null;
		try {
			if (initialTemplateId !== null) {
				// Bare-object endpoint (no envelope) — read res.data directly.
				const res = await api.GET('/api/v2/titlegen/templates/{template_id}', {
					params: { path: { template_id: initialTemplateId } }
				});
				if (!res.data) throw toApiError(undefined, res.response);
				const t = res.data as TitleTemplate;
				templateId = t.id;
				name = t.name;
				description = t.description;
				defaultDuration = t.default_duration;
				const cfg = t.template_config as Partial<TTTemplateConfig>;
				initialConfig = {
					canvas: cfg.canvas ?? { width: 1920, height: 1080 },
					elements: cfg.elements ?? []
				};
			}
			metaDirty = false;
		} catch (e) {
			loadError = toApiError(e);
		}
		loading = false;
	}
	void loadTemplate();

	// Create the engine once the canvas is in the DOM (after load resolves).
	$effect(() => {
		if (!stageEl || editor) return;
		const ed = new TitleCanvasEditor(stageEl, host);
		editor = ed;
		ed.loadConfig(initialConfig);
		fit();
		// Re-render with the real metrics once the bundled faces land.
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

	function fit() {
		if (!editor) return;
		editor.calculateOptimalZoom(containerEl?.clientWidth ?? 840);
		editor.render();
	}

	// `tick >= 0` is always true; reading it re-derives on every editor change.
	const elementCount = $derived(tick >= 0 ? (editor?.config.elements.length ?? 0) : 0);
	const zoomPercent = $derived(tick >= 0 ? Math.round((editor?.zoom ?? 0.4) * 100) : 0);
	const dirty = $derived(tick >= 0 && ((editor?.isDirty ?? false) || metaDirty));
	$effect(() => {
		dirtyOut = dirty;
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
		const target = e.target as HTMLElement;
		if (/^(input|select|textarea)$/i.test(target.tagName || '') || target.isContentEditable) return;
		editor?.handleKeyDown(e);
	}

	let saving = $state(false);

	async function saveTemplate() {
		// The Save button is disabled until there is a name and an element (canSave).
		if (!editor) return;
		const payload = {
			name: name.trim(),
			description,
			default_duration: defaultDuration,
			template_config: editor.config as unknown as Record<string, never>
		};

		saving = true;
		try {
			const saved = (await raw(
				templateId
					? api.PUT('/api/v2/titlegen/templates/{template_id}', {
							params: { path: { template_id: templateId } },
							body: payload
						})
					: api.POST('/api/v2/titlegen/templates', { body: payload })
			)) as TitleTemplate;
			discardChanges();
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
	unwrap(api.GET('/api/v2/programmes/list')).then(
		(data) => (programmes = data?.programmes ?? []),
		(e) => console.error('Failed to load programmes for preview:', e)
	);

	let previewProgrammeId = $state('');

	// A rundown row's `details` is untyped in the schema; movie rows carry movie_id.
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
					const m: Partial<MovieDetail> = await unwrap(
						api.GET('/api/v2/movies/{movie_id}', {
							params: { path: { movie_id: it.details!.movie_id! } }
						})
					).catch(() => ({}));
					return {
						title: m.title || it.title || '',
						director: m.director || '',
						year: m.year != null ? String(m.year) : '',
						certification: m.certification || '',
						runtime: m.runtime != null ? `${m.runtime} min` : '',
						poster: m.thumbnail_url || ''
					};
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
</script>

<svelte:window onbeforeunload={onBeforeUnload} onkeydown={onKeyDown} onresize={fit} />
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
	<ErrorState error={loadError} retry={() => void loadTemplate()} />
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
					<Button size="sm" title="Fit to screen" onclick={fit}><Expand size={13} /></Button>
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
					{@render textField('Template name *', 'e.g. Double feature', name, (v) => (name = v))}
					{@render textField(
						'Description',
						'Optional description',
						description,
						(v) => (description = v)
					)}
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
		{@render menuItem(Copy, 'Duplicate', () => ed.duplicateSelected())}
		{#if menu.single}
			{@render menuItem(ArrowUp, 'Bring forward', () => ed.moveElement(menu.hit, 1))}
			{@render menuItem(ArrowDown, 'Send backward', () => ed.moveElement(menu.hit, -1))}
		{/if}
		<hr class="my-1 border-border" />
		{@render menuItem(Trash2, 'Delete', () => ed.deleteSelected(), 'text-danger hover:text-danger')}
	</div>
{/if}

{#snippet textField(label: string, placeholder: string, value: string, set: (v: string) => void)}
	<label class={labelCls}>
		{label}
		<input
			type="text"
			class={fieldCls}
			{placeholder}
			{value}
			oninput={(e) => {
				set(e.currentTarget.value);
				metaDirty = true;
			}}
		/>
	</label>
{/snippet}

{#snippet menuItem(Icon: typeof Copy, label: string, fn: () => void, cls = '')}
	<button
		type="button"
		class="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm text-text hover:bg-surface-3 {cls}"
		onclick={() => {
			fn();
			ctxMenu = null;
		}}
	>
		<Icon size={13} />
		{label}
	</button>
{/snippet}
