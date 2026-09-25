<script lang="ts">
	import {
		ArrowUpDown,
		Barcode,
		BadgeCheck,
		ChevronDown,
		ChevronUp,
		Copy,
		Image,
		Minus,
		Plus,
		QrCode,
		Star,
		Trash2,
		Type,
		Upload,
		X
	} from '@lucide/svelte';
	import type { Component } from 'svelte';
	import type { LucideIcon } from '@lucide/svelte';
	import { api } from '$lib/api/client';
	import { raw } from '$lib/settings/form.svelte';
	import { showToast } from '$lib/toast.svelte';
	import { uploadWithProgress } from '$lib/upload';
	import type { components } from '$lib/api/types.gen';
	import type { TicketDesignMeta, TicketElement, TicketPreviewOp } from '$lib/settings/types';

	type TicketImage = components['schemas']['TicketImageSchema'];
	import Button from '$lib/components/ui/Button.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import type ConfirmDialog from '$lib/components/ConfirmDialog.svelte';

	interface Props {
		confirm: ConfirmDialog['confirm'];
	}
	let { confirm }: Props = $props();

	interface DesignSummary {
		id: number;
		name: string;
		is_default: boolean;
	}
	interface Design extends DesignSummary {
		elements: TicketElement[];
	}

	const PRESETS: { label: string; icon: LucideIcon; make: () => TicketElement }[] = [
		{ label: 'Text', icon: Type, make: () => ({ type: 'text', content: 'Text' }) },
		{ label: 'Image', icon: Image, make: () => ({ type: 'image' }) },
		{ label: 'Rating symbol', icon: BadgeCheck, make: () => ({ type: 'rating', scale: 'medium' }) },
		{ label: 'QR code', icon: QrCode, make: () => ({ type: 'qr', mode: 'fun', size: 6 }) },
		{ label: 'Barcode', icon: Barcode, make: () => ({ type: 'barcode', content: '{ticket_no}' }) },
		{ label: 'Divider', icon: Minus, make: () => ({ type: 'rule' }) },
		{ label: 'Spacer', icon: ArrowUpDown, make: () => ({ type: 'spacer', lines: 1 }) }
	];
	const ICONS: Record<string, LucideIcon> = {
		text: Type,
		image: Image,
		rating: BadgeCheck,
		qr: QrCode,
		barcode: Barcode,
		rule: Minus,
		spacer: ArrowUpDown
	};

	const TOKEN_HINTS: Record<string, string> = {
		film: "The feature's title - only when the programme has exactly one feature (blank otherwise; use {film_list} for the general case)",
		film_list: 'One line per feature in the programme - title, year and certificate',
		showtime: 'Date + time of the scheduled screening - blank when printing without a showtime',
		programme: "The programme's name",
		ticket_no: 'The running ticket number'
	};

	function elementLabel(el: TicketElement): string {
		switch (el.type) {
			case 'text':
				return el.content ? `"${el.content.replace(/\n/g, ' ').slice(0, 28)}"` : 'Text';
			case 'image':
				return el.file || 'Image';
			case 'rating':
				return 'Rating symbol';
			case 'qr':
				return el.mode === 'fun' ? 'QR (surprise link)' : 'QR code';
			case 'barcode':
				return 'Barcode';
			case 'rule':
				return 'Divider';
			case 'spacer':
				return `Spacer (${el.lines || 1})`;
			default:
				return el.type;
		}
	}

	let designs = $state<DesignSummary[]>([]);
	let current = $state<Design | null>(null);
	let selected = $state(-1);
	let meta = $state<TicketDesignMeta | null>(null);
	let loading = $state(true);
	let selectValue = $state('');
	let designName = $state('');
	let addOpen = $state(false);
	let previewTab = $state<'styled' | 'text'>('styled');

	let addWrap: HTMLDivElement | undefined = $state();
	function onWindowClick(e: MouseEvent) {
		if (addOpen && addWrap && !addWrap.contains(e.target as Node)) addOpen = false;
	}

	let savePending: ReturnType<typeof setTimeout> | null = null;
	let previewPending: ReturnType<typeof setTimeout> | null = null;

	$effect(() => {
		void init();
		return () => {
			if (savePending) clearTimeout(savePending);
			if (previewPending) clearTimeout(previewPending);
		};
	});

	async function init() {
		meta = await raw<TicketDesignMeta>(api.GET('/api/v2/tickets/designs/meta')).catch(() => null);
		await loadDesigns();
		loading = false;
		void loadImages(); // supplementary — the image picker degrades to logo-only
	}

	let images = $state<TicketImage[]>([]);
	let imageInput: HTMLInputElement | undefined = $state();
	let uploadingImage = $state(false);

	async function loadImages() {
		try {
			images = await raw(api.GET('/api/v2/tickets/images'));
		} catch {
			// Leave whatever we had.
		}
	}

	async function onImagePicked() {
		const file = imageInput?.files?.[0];
		if (!file || !current || selected < 0) return;
		uploadingImage = true;
		try {
			const created = await uploadWithProgress<TicketImage>(
				'/api/v2/tickets/images/upload',
				file,
				{},
				undefined,
				'image'
			);
			await loadImages();
			const el = current.elements[selected];
			if (el?.type === 'image') {
				el.file = created.name;
				commit();
			}
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Image upload failed', 'error');
		} finally {
			uploadingImage = false;
			if (imageInput) imageInput.value = '';
		}
	}

	function setImageFile(el: TicketElement, file: string) {
		el.file = file;
		delete el.source; // legacy field; image elements are file-only now
		commit();
	}

	async function loadDesigns() {
		try {
			designs = await raw(api.GET('/api/v2/tickets/designs'));
		} catch {
			showToast('Failed to load ticket designs', 'error');
			return;
		}
		const pick =
			current && designs.some((d) => d.id === current!.id)
				? current!.id
				: (designs.find((d) => d.is_default) || designs[0])?.id;
		if (pick) await selectDesign(pick);
	}

	async function selectDesign(id: number) {
		try {
			current = (await raw(
				api.GET('/api/v2/tickets/designs/{design_id}', {
					params: { path: { design_id: id } }
				})
			)) as Design;
		} catch {
			showToast('Failed to load design', 'error');
			return;
		}
		selected = current.elements.length ? 0 : -1;
		selectValue = String(current.id);
		designName = current.name;
		schedulePreview();
	}

	function selectRow(i: number) {
		selected = selected === i ? -1 : i;
	}

	function move(i: number, delta: number) {
		if (!current) return;
		const els = current.elements;
		const j = i + delta;
		if (j < 0 || j >= els.length) return;
		// splice out + reinsert (not a destructuring swap) so the keyed rows
		// genuinely reorder; refocus keeps repeated Enter presses moving the same one.
		const [el] = els.splice(i, 1);
		els.splice(j, 0, el);
		if (selected === i) selected = j;
		else if (selected === j) selected = i;
		requestAnimationFrame(() => {
			document
				.querySelector<HTMLButtonElement>(`[data-move="${j}:${delta}"]`)
				?.focus({ preventScroll: true });
		});
		commit();
	}

	function remove(i: number) {
		if (!current) return;
		current.elements.splice(i, 1);
		if (selected >= current.elements.length) selected = current.elements.length - 1;
		commit();
	}

	function add(el: TicketElement) {
		if (!current) return;
		addOpen = false;
		const at = selected >= 0 ? selected + 1 : current.elements.length;
		current.elements.splice(at, 0, el);
		selected = at;
		commit();
	}

	function insertToken(token: string) {
		const field = document.getElementById('td-content-input') as
			HTMLInputElement | HTMLTextAreaElement | null;
		if (!field || !current || selected < 0) return;
		const start = field.selectionStart ?? field.value.length;
		const end = field.selectionEnd ?? field.value.length;
		const ins = `{${token}}`;
		const value = field.value.slice(0, start) + ins + field.value.slice(end);
		current.elements[selected].content = value;
		const pos = start + ins.length;
		requestAnimationFrame(() => {
			field.focus();
			field.setSelectionRange(pos, pos);
		});
		commit();
	}

	function commit() {
		scheduleSave();
		schedulePreview();
	}

	function scheduleSave() {
		if (savePending) clearTimeout(savePending);
		savePending = setTimeout(() => void save(), 500);
	}

	async function save() {
		if (!current) return;
		const name = designName.trim() || 'Untitled';
		try {
			const updated = (await raw(
				api.PUT('/api/v2/tickets/designs/{design_id}', {
					params: { path: { design_id: current.id } },
					body: { name, elements: $state.snapshot(current.elements) }
				})
			)) as Design;
			current.name = updated.name;
			const summary = designs.find((d) => d.id === updated.id);
			if (summary) summary.name = updated.name;
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Failed to save design', 'error');
		}
	}

	let previewLines = $state<string[]>([]);
	let previewOps = $state<TicketPreviewOp[]>([]);
	let paperWidth = $state(384);
	let previewReady = $state(false);

	function schedulePreview() {
		if (previewPending) clearTimeout(previewPending);
		previewPending = setTimeout(() => void preview(), 300);
	}

	async function preview() {
		if (!current) return;
		try {
			const data = await raw(
				api.POST('/api/v2/tickets/preview', {
					body: { elements: $state.snapshot(current.elements) }
				})
			);
			previewLines = data.data.lines ?? [];
			previewOps = (data.data.ops ?? []) as unknown as TicketPreviewOp[];
			paperWidth = data.data.paper_width ?? 384;
			previewReady = true;
		} catch {
			// Preview is supplementary — keep the last good one.
		}
	}

	// Receipt strip: 1 printer dot = 0.75 px.
	const SCALE = 0.75;
	const stripWidth = $derived(Math.round(paperWidth * SCALE));

	function opClasses(op: TicketPreviewOp): string {
		let cls = '';
		if (op.align === 'left') cls += ' strip-left';
		if (op.align === 'right') cls += ' strip-right';
		if (op.size && op.size !== 'normal') cls += ` strip-${op.size}`;
		if (op.bold) cls += ' strip-bold';
		if (op.invert) cls += ' strip-invert';
		return cls;
	}

	function textLines(value: string): string[] {
		const lines = value.split('\n');
		if (lines[lines.length - 1] === '') lines.pop();
		return lines;
	}

	async function newDesign() {
		try {
			const d = await raw(
				api.POST('/api/v2/tickets/designs', {
					body: {
						name: 'New design',
						elements: [{ type: 'text', content: '{cinema}', bold: true }]
					}
				})
			);
			await loadDesigns();
			await selectDesign(d.id);
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Could not create design', 'error');
		}
	}

	async function duplicate() {
		if (!current) return;
		try {
			const d = await raw(
				api.POST('/api/v2/tickets/designs/{design_id}/duplicate', {
					params: { path: { design_id: current.id } }
				})
			);
			await loadDesigns();
			await selectDesign(d.id);
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Could not duplicate', 'error');
		}
	}

	async function setDefault() {
		if (!current) return;
		try {
			await raw(
				api.PUT('/api/v2/tickets/designs/{design_id}', {
					params: { path: { design_id: current.id } },
					body: { is_default: true }
				})
			);
			current.is_default = true;
			await loadDesigns();
			showToast('Default design set', 'success');
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Could not set default', 'error');
		}
	}

	async function deleteCurrent() {
		if (!current || designs.length <= 1) return;
		if (!(await confirm(`Delete design "${current.name}"?`, { confirmLabel: 'Delete' }))) return;
		try {
			await raw(
				api.DELETE('/api/v2/tickets/designs/{design_id}', {
					params: { path: { design_id: current.id } }
				})
			);
			current = null;
			await loadDesigns();
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Could not delete', 'error');
		}
	}

	const alignments = $derived(meta?.alignments ?? ['center', 'left', 'right']);
	const sizes = $derived(meta?.sizes ?? ['normal', 'wide', 'tall', 'large']);
	const ratingScales = $derived(meta?.rating_scales ?? ['small', 'medium', 'large']);
	const tokens = $derived(meta?.tokens ?? []);

	const cfgLabelCls = 'mb-1 block text-xs font-medium text-muted';
	const cfgInputCls =
		'w-full rounded-md border border-border-strong bg-surface-2 px-2 py-1.5 text-sm text-text focus:border-accent-dim';
</script>

<svelte:window onclick={onWindowClick} />

{#if loading}
	<Spinner label="Loading ticket designs…" />
{:else if !current}
	<p class="text-sm text-muted">No ticket designs could be loaded.</p>
	<Button size="sm" class="mt-2" onclick={() => void loadDesigns()}>Try again</Button>
{:else}
	<div class="mb-3 flex flex-wrap items-center gap-2">
		<Select
			bind:value={selectValue}
			onchange={() => void selectDesign(parseInt(selectValue, 10))}
			class="min-w-44"
		>
			{#each designs as d (d.id)}
				<option value={String(d.id)}>{d.name}{d.is_default ? ' (default)' : ''}</option>
			{/each}
		</Select>
		<Button size="sm" onclick={newDesign}><Plus size={13} /> New</Button>
		<Button size="sm" onclick={duplicate}><Copy size={13} /> Duplicate</Button>
		<Button size="sm" disabled={current.is_default} onclick={setDefault}>
			<Star size={13} /> Set default
		</Button>
		<Button size="sm" variant="danger" disabled={designs.length <= 1} onclick={deleteCurrent}>
			<Trash2 size={13} /> Delete
		</Button>
	</div>

	<div class="mb-4 flex flex-wrap items-center gap-2">
		<label class="text-xs font-medium text-muted" for="td-name">Name</label>
		<Input
			id="td-name"
			bind:value={designName}
			oninput={scheduleSave}
			placeholder="Design name"
			class="max-w-64"
		/>
		{#if current.is_default}
			<span
				class="flex items-center gap-1 rounded-sm bg-accent/15 px-1.5 py-0.5 text-[0.7rem] font-medium text-accent"
			>
				<Star size={11} /> Default
			</span>
		{/if}
		<span class="text-xs text-faint">
			Changes save automatically. Assign a design to a programme from its box-office panel.
		</span>
	</div>

	<div class="grid gap-4 lg:grid-cols-2">
		<div>
			<div class="mb-2 flex items-center justify-between">
				<h3 class="text-xs font-medium text-muted">
					Elements <span class="font-sans font-normal normal-case">- click to edit</span>
				</h3>
				<div class="relative" bind:this={addWrap}>
					<Button size="sm" onclick={() => (addOpen = !addOpen)}><Plus size={13} /> Add</Button>
					{#if addOpen}
						<div
							class="absolute right-0 z-10 mt-1 w-44 rounded-md border border-border-strong bg-surface-1 py-1"
						>
							{#each PRESETS as p (p.label)}
								<button
									type="button"
									class="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-surface-2"
									onclick={() => add(p.make())}
								>
									<p.icon size={14} class="text-muted" />
									{p.label}
								</button>
							{/each}
						</div>
					{/if}
				</div>
			</div>

			{#if !current.elements.length}
				<p class="rounded-md border border-border px-3 py-4 text-sm text-muted">
					No elements yet - add one.
				</p>
			{:else}
				<!-- Keyed by element identity (not index) so a move reorders real rows. -->
				<ul class="space-y-1">
					{#each current.elements as el, i (el)}
						{@const open = i === selected}
						{@const RowIcon = ICONS[el.type] ?? Type}
						<li
							class="rounded-md border {open
								? 'border-border-strong bg-surface-2'
								: 'border-border'}"
						>
							<div class="flex items-center gap-2 px-2.5 py-1.5">
								<button
									type="button"
									class="flex min-w-0 flex-1 items-center gap-2 text-left text-sm"
									onclick={() => selectRow(i)}
								>
									<RowIcon size={14} class="shrink-0 text-muted" />
									<span class="min-w-0 truncate">{elementLabel(el)}</span>
								</button>
								<span class="flex shrink-0 items-center gap-0.5">
									<button
										type="button"
										class="rounded-sm p-1 text-muted hover:bg-surface-3 hover:text-text disabled:opacity-30"
										title="Move up"
										data-move="{i}:-1"
										disabled={i === 0}
										onclick={() => move(i, -1)}
									>
										<ChevronUp size={14} />
									</button>
									<button
										type="button"
										class="rounded-sm p-1 text-muted hover:bg-surface-3 hover:text-text disabled:opacity-30"
										title="Move down"
										data-move="{i}:1"
										disabled={i === current.elements.length - 1}
										onclick={() => move(i, 1)}
									>
										<ChevronDown size={14} />
									</button>
									<button
										type="button"
										class="rounded-sm p-1 text-muted hover:bg-surface-3 hover:text-danger"
										title="Remove"
										onclick={() => remove(i)}
									>
										<X size={14} />
									</button>
								</span>
							</div>

							{#if open}
								<div class="space-y-3 border-t border-border px-3 py-3">
									{#if el.type === 'text'}
										<label class="block">
											<span class={cfgLabelCls}>Content</span>
											<textarea
												id="td-content-input"
												rows="2"
												class="{cfgInputCls} font-mono"
												value={el.content ?? ''}
												oninput={(e) => {
													el.content = (e.currentTarget as HTMLTextAreaElement).value;
													commit();
												}}></textarea>
										</label>
									{:else if el.type === 'barcode'}
										<label class="block">
											<span class={cfgLabelCls}>Content</span>
											<input
												id="td-content-input"
												type="text"
												class="{cfgInputCls} font-mono"
												value={el.content ?? ''}
												oninput={(e) => {
													el.content = (e.currentTarget as HTMLInputElement).value;
													commit();
												}}
											/>
										</label>
									{:else if el.type === 'rating'}
										<label class="block max-w-40">
											<span class={cfgLabelCls}>Size</span>
											<select
												class={cfgInputCls}
												value={el.scale ?? 'medium'}
												onchange={(e) => {
													el.scale = (e.currentTarget as HTMLSelectElement).value;
													commit();
												}}
											>
												{#each ratingScales as s (s)}
													<option value={s}>{s}</option>
												{/each}
											</select>
										</label>
										<p class="text-xs text-faint">
											The programme's certificate - the most restrictive among its features.
										</p>
									{:else if el.type === 'qr'}
										<div class="flex flex-wrap gap-3">
											<label class="block max-w-44">
												<span class={cfgLabelCls}>Mode</span>
												<select
													class={cfgInputCls}
													value={el.mode === 'fun' ? 'fun' : 'content'}
													onchange={(e) => {
														el.mode = (e.currentTarget as HTMLSelectElement).value;
														commit();
													}}
												>
													<option value="fun">Surprise link</option>
													<option value="content">Content</option>
												</select>
											</label>
											<label class="block max-w-24">
												<span class={cfgLabelCls}>Size</span>
												<input
													type="number"
													min="1"
													max="16"
													class={cfgInputCls}
													value={String(el.size ?? 6)}
													oninput={(e) => {
														el.size =
															parseInt((e.currentTarget as HTMLInputElement).value, 10) || 6;
														commit();
													}}
												/>
											</label>
										</div>
										{#if el.mode === 'fun'}
											<p class="text-xs text-faint">
												Picks a random link from the pool in Ticket defaults.
											</p>
										{:else}
											<label class="block">
												<span class={cfgLabelCls}>Content</span>
												<input
													type="text"
													class="{cfgInputCls} font-mono"
													value={el.content ?? ''}
													oninput={(e) => {
														el.content = (e.currentTarget as HTMLInputElement).value;
														commit();
													}}
												/>
											</label>
										{/if}
									{:else if el.type === 'spacer'}
										<label class="block max-w-28">
											<span class={cfgLabelCls}>Blank lines</span>
											<input
												type="number"
												min="1"
												max="10"
												class={cfgInputCls}
												value={String(el.lines ?? 1)}
												oninput={(e) => {
													el.lines = parseInt((e.currentTarget as HTMLInputElement).value, 10) || 1;
													commit();
												}}
											/>
										</label>
									{:else if el.type === 'image'}
										<div>
											<span class={cfgLabelCls}>Image</span>
											<div class="flex flex-wrap gap-2">
												{#each images as img (img.name)}
													<button
														type="button"
														class="flex items-center gap-2 rounded-md border px-2 py-1.5 text-sm
															{el.file === img.name
															? 'border-accent bg-accent/10 text-text'
															: 'border-border-strong bg-surface-2 text-muted hover:text-text'}"
														title={img.width && img.height
															? `${img.width}×${img.height}`
															: img.name}
														onclick={() => setImageFile(el, img.name)}
													>
														<img
															src={img.url}
															alt=""
															class="h-8 w-8 rounded-xs bg-white object-contain p-0.5"
														/>
														<span class="max-w-32 truncate">{img.name}</span>
													</button>
												{/each}
												<button
													type="button"
													class="flex items-center gap-1.5 rounded-md border border-dashed border-border-strong px-2 py-1.5 text-sm text-muted hover:border-accent-dim hover:text-text disabled:opacity-45"
													disabled={uploadingImage}
													onclick={() => imageInput?.click()}
												>
													<Upload size={13} />
													{uploadingImage ? 'Uploading…' : 'Upload…'}
												</button>
											</div>
											<p class="mt-1.5 text-xs text-faint">
												The logo is set under Box office → Images, where library images are managed
												too. Images print dithered to 1-bit - bold, high-contrast art works best.
											</p>
										</div>
									{/if}

									{#if (el.type === 'text' || el.type === 'barcode') && tokens.length}
										<div class="flex flex-wrap items-center gap-1">
											<span class="text-xs text-faint">Insert:</span>
											{#each tokens as t (t)}
												<button
													type="button"
													class="rounded-sm border border-border-strong bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-muted hover:bg-surface-3 hover:text-text"
													title={TOKEN_HINTS[t] || `Insert {${t}}`}
													onclick={() => insertToken(t)}
												>
													{t}
												</button>
											{/each}
										</div>
									{/if}

									{#if el.type !== 'rule' && el.type !== 'spacer'}
										<div class="flex flex-wrap items-end gap-3">
											<label class="block max-w-36">
												<span class={cfgLabelCls}>Align</span>
												<select
													class={cfgInputCls}
													value={el.align ?? 'center'}
													onchange={(e) => {
														el.align = (e.currentTarget as HTMLSelectElement).value;
														commit();
													}}
												>
													{#each alignments as a (a)}
														<option value={a}>{a}</option>
													{/each}
												</select>
											</label>
											{#if el.type === 'text'}
												<label class="block max-w-36">
													<span class={cfgLabelCls}>Size</span>
													<select
														class={cfgInputCls}
														value={typeof el.size === 'string' ? el.size : 'normal'}
														onchange={(e) => {
															el.size = (e.currentTarget as HTMLSelectElement).value;
															commit();
														}}
													>
														{#each sizes as s (s)}
															<option value={s}>{s}</option>
														{/each}
													</select>
												</label>
												<label class="flex items-center gap-1.5 pb-2 text-sm">
													<input
														type="checkbox"
														class="accent-accent"
														checked={!!el.bold}
														onchange={(e) => {
															el.bold = (e.currentTarget as HTMLInputElement).checked;
															commit();
														}}
													/>
													Bold
												</label>
												<label class="flex items-center gap-1.5 pb-2 text-sm">
													<input
														type="checkbox"
														class="accent-accent"
														checked={!!el.invert}
														onchange={(e) => {
															el.invert = (e.currentTarget as HTMLInputElement).checked;
															commit();
														}}
													/>
													Invert
												</label>
											{/if}
										</div>
									{/if}
								</div>
							{/if}
						</li>
					{/each}
				</ul>
			{/if}
		</div>

		<div>
			<div class="mb-2 flex items-center justify-between">
				<h3 class="text-xs font-medium text-muted">Preview</h3>
				<div class="flex gap-1">
					{#each [{ id: 'styled', label: 'Styled' }, { id: 'text', label: 'Text' }] as t (t.id)}
						<button
							type="button"
							class="rounded-sm px-2 py-1 text-xs font-medium
								{previewTab === t.id ? 'bg-surface-3 text-text' : 'text-muted hover:text-text'}"
							onclick={() => (previewTab = t.id as 'styled' | 'text')}
						>
							{t.label}
						</button>
					{/each}
				</div>
			</div>

			{#if !previewReady}
				<Spinner size="sm" label="Rendering preview…" />
			{:else if previewTab === 'styled'}
				<div class="strip mx-auto" style="width: {stripWidth}px">
					{#each previewOps as op, i (i)}
						{#if op.type === 'text'}
							{#each textLines(op.value) as line, li (li)}
								<div class="strip-line{opClasses(op)}">{line || ' '}</div>
							{/each}
						{:else if op.type === 'image'}
							<div class="strip-media{opClasses(op)}">
								<img
									src={op.url}
									alt={op.kind}
									style="width:{Math.round(op.width_px * SCALE)}px;height:{Math.round(
										op.height_px * SCALE
									)}px"
								/>
							</div>
						{:else if op.type === 'qr'}
							{@const px = Math.round(op.size * 8 * SCALE)}
							<div class="strip-media{opClasses(op)}">
								<span class="strip-qr" style="width:{px}px;height:{px}px">
									<QrCode size={22} />
								</span>
							</div>
						{:else if op.type === 'barcode'}
							<div class="strip-media{opClasses(op)}">
								<span class="strip-barcode"><Barcode size={22} /> {op.value}</span>
							</div>
						{/if}
					{/each}
				</div>
			{:else}
				<pre
					class="overflow-x-auto rounded-md border border-border bg-surface-2 p-3 font-mono text-xs leading-relaxed">{previewLines.join(
						'\n'
					)}</pre>
			{/if}
		</div>
	</div>

	<input
		type="file"
		bind:this={imageInput}
		accept="image/png,image/jpeg,image/gif"
		hidden
		onchange={onImagePicked}
	/>
{/if}

<style>
	/* The receipt strip is deliberately paper-coloured — it previews thermal paper, not the app theme. */
	.strip {
		padding: 16px 0 10px;
		background: #fdfcf7;
		color: #111;
		border: 1px solid var(--color-border, #333);
		box-shadow: inset 0 0 24px rgba(0, 0, 0, 0.06);
		display: flex;
		flex-direction: column;
		align-items: center;
		overflow: hidden;
	}
	.strip-line {
		width: 100%;
		text-align: center;
		font-family: var(--font-mono, monospace);
		font-size: 15px;
		line-height: 1.35;
		white-space: pre;
		overflow: hidden;
	}
	.strip-left {
		text-align: left;
		align-self: stretch;
	}
	.strip-right {
		text-align: right;
		align-self: stretch;
	}
	.strip-wide {
		transform: scaleX(2);
		transform-origin: center;
	}
	.strip-tall {
		transform: scaleY(2);
		transform-origin: center;
		margin: 0.35em 0;
	}
	.strip-large {
		font-size: 30px;
		line-height: 1.2;
	}
	.strip-bold {
		font-weight: 700;
	}
	.strip-invert {
		background: #111;
		color: #fdfcf7;
	}
	.strip-media {
		display: flex;
		justify-content: center;
		width: 100%;
		margin: 4px 0;
	}
	.strip-left.strip-media {
		justify-content: flex-start;
	}
	.strip-right.strip-media {
		justify-content: flex-end;
	}
	.strip-media img {
		filter: grayscale(1) contrast(1.4);
	}
	.strip-qr {
		display: flex;
		align-items: center;
		justify-content: center;
		border: 2px dashed #999;
		color: #999;
	}
	.strip-barcode {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 4px 10px;
		border: 2px dashed #999;
		color: #777;
		font-family: var(--font-mono, monospace);
		font-size: 12px;
	}
</style>
