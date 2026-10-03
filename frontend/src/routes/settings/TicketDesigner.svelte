<script lang="ts">
	// Ticket designs, ticket first: pick a design from the row at the top, click a line on the
	// receipt to edit it beside it (drag lines to reorder them), and set the design's name, font,
	// date and time formats and surprise links below. Everything saves as you go, with undo.
	import { Copy, Ellipsis, Plus, Printer, Redo2, Star, Trash2, Undo2 } from '@lucide/svelte';
	import { ChevronDown, ChevronUp } from '@lucide/svelte';
	import { api, unwrap } from '$lib/api/client';
	import { raw } from '$lib/settings/form.svelte';
	import { showToast } from '$lib/toast.svelte';
	import Field from '$lib/settings/Field.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Menu, { type MenuItem } from '$lib/components/ui/Menu.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import type ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import ColumnsFields from '$lib/tickets/ColumnsFields.svelte';
	import ItemFields from '$lib/tickets/ItemFields.svelte';
	import Receipt from '$lib/tickets/Receipt.svelte';
	import { History } from '$lib/tickets/history';
	import {
		DATE_FORMATS,
		FONTS,
		KINDS,
		STARTERS,
		TIME_FORMATS,
		kindOf,
		setField,
		type Design,
		type DesignDraft,
		type Element,
		type Preview,
		type Selection,
		type TicketElement
	} from '$lib/tickets/kinds';
	import Disclosure from './Disclosure.svelte';

	interface Props {
		confirm: ConfirmDialog['confirm'];
	}
	let { confirm }: Props = $props();

	type Summary = Pick<Design, 'id' | 'name' | 'is_default'>;

	let designs = $state<Summary[]>([]);
	let current = $state<Design | null>(null);
	let selection = $state<Selection | null>(null);
	let loading = $state(true);

	const history = new History<DesignDraft>();
	let canUndo = $state(false);
	let canRedo = $state(false);

	let savePending: ReturnType<typeof setTimeout> | null = null;
	let previewPending: ReturnType<typeof setTimeout> | null = null;

	$effect(() => {
		void loadDesigns().then(() => (loading = false));
		return () => {
			if (savePending) clearTimeout(savePending);
			if (previewPending) clearTimeout(previewPending);
		};
	});

	// ── Loading ───────────────────────────────────────────────────────────────────

	async function loadDesigns() {
		try {
			designs = await raw(api.GET('/api/v2/tickets/designs'));
		} catch {
			showToast('Failed to load ticket designs', 'error');
			return;
		}
		const keep = current && designs.some((d) => d.id === current!.id) ? current.id : null;
		const pick = keep ?? (designs.find((d) => d.is_default) ?? designs[0])?.id;
		if (pick) await openDesign(pick);
	}

	async function openDesign(id: number) {
		try {
			current = (await raw(
				api.GET('/api/v2/tickets/designs/{design_id}', { params: { path: { design_id: id } } })
			)) as Design;
		} catch {
			showToast('Failed to load design', 'error');
			return;
		}
		selection = current.elements.length ? { index: 0 } : null;
		history.reset(draft());
		syncHistory();
		schedulePreview();
	}

	// ── Editing: every change goes through edit(), which records it for undo and saves ──

	function draft(): DesignDraft {
		const { name, elements, date_format, time_format, qr_links, font } = $state.snapshot(current!);
		return { name, elements, date_format, time_format, qr_links, font };
	}

	/** The editor's loose elements are the API's elements (kinds.ts checks they fit). */
	function forApi<T extends { elements: TicketElement[] }>(fields: T) {
		return { ...fields, elements: fields.elements as Element[] };
	}

	function syncHistory() {
		canUndo = history.canUndo;
		canRedo = history.canRedo;
	}

	/** Apply `mutate` to the design; `key` merges a burst of edits to one field into one undo step. */
	function edit(mutate: (design: Design) => void, key = '') {
		if (!current) return;
		mutate(current);
		history.record(draft(), key);
		syncHistory();
		scheduleSave();
		schedulePreview();
	}

	const lineAt = (design: Design) => design.elements[selection!.index];

	function restore(snapshot: DesignDraft | null) {
		if (!current || !snapshot) return;
		Object.assign(current, snapshot);
		if (selection && selection.index >= current.elements.length) {
			selection = current.elements.length ? { index: current.elements.length - 1 } : null;
		}
		const line = selection && current.elements[selection.index];
		if (selection?.cell !== undefined && line?.type !== 'columns')
			selection = { index: selection.index };
		syncHistory();
		scheduleSave();
		schedulePreview();
	}
	const undo = () => restore(history.undo(draft()));
	const redo = () => restore(history.redo(draft()));

	function onKeydown(e: KeyboardEvent) {
		if (!current || !(e.metaKey || e.ctrlKey)) return;
		// Text fields keep their own undo.
		if ((e.target as HTMLElement).closest('input, textarea, select, [contenteditable]')) return;
		const key = e.key.toLowerCase();
		if (key === 'z' || key === 'y') {
			e.preventDefault();
			if (key === 'y' || e.shiftKey) redo();
			else undo();
		}
	}

	function add(el: TicketElement) {
		const at = selection ? selection.index + 1 : (current?.elements.length ?? 0);
		edit((d) => d.elements.splice(at, 0, el));
		selection = { index: at };
	}

	function move(from: number, to: number) {
		if (!current || to < 0 || to >= current.elements.length) return;
		edit((d) => {
			const [el] = d.elements.splice(from, 1);
			d.elements.splice(to, 0, el);
		});
		selection = { index: to };
	}

	function remove(index: number) {
		edit((d) => d.elements.splice(index, 1));
		const left = current?.elements.length ?? 0;
		selection = left ? { index: Math.min(index, left - 1) } : null;
	}

	// ── Saving, preview, test print ───────────────────────────────────────────

	function scheduleSave() {
		if (savePending) clearTimeout(savePending);
		savePending = setTimeout(() => void save(), 500);
	}

	async function save() {
		if (!current) return;
		const { name, ...fields } = draft();
		try {
			const updated = (await raw(
				api.PUT('/api/v2/tickets/designs/{design_id}', {
					params: { path: { design_id: current.id } },
					body: { name: name.trim() || 'Untitled', ...forApi(fields) }
				})
			)) as Design;
			const summary = designs.find((d) => d.id === updated.id);
			if (summary) summary.name = updated.name;
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Failed to save design', 'error');
		}
	}

	let previewImage = $state<Preview | null>(null);

	function schedulePreview() {
		if (previewPending) clearTimeout(previewPending);
		previewPending = setTimeout(() => void preview(), 300);
	}

	async function preview() {
		if (!current) return;
		const { name: _name, ...design } = draft();
		try {
			const data = await raw(
				api.POST('/api/v2/tickets/preview', { body: { design: forApi(design) } })
			);
			previewImage = data.data;
		} catch {
			// The preview is supplementary: keep the last good one.
		}
	}

	let printing = $state(false);
	async function testPrint() {
		if (!current) return;
		printing = true;
		const { name: _name, ...design } = draft();
		try {
			const data = await unwrap(
				api.POST('/api/v2/tickets/test', { body: { include_seat: true, design: forApi(design) } })
			);
			showToast(`Test ticket printed${data.seat ? ` (seat ${data.seat})` : ''}`, 'success');
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Failed to print test ticket', 'error');
		} finally {
			printing = false;
		}
	}

	// ── Designs ───────────────────────────────────────────────────────────────

	async function newDesign(starter: (typeof STARTERS)[number]['id']) {
		try {
			const d = await raw(
				api.POST('/api/v2/tickets/designs', { body: { name: 'New design', starter } })
			);
			await loadDesigns();
			await openDesign(d.id);
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
			await openDesign(d.id);
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

	const starterItems: MenuItem[] = STARTERS.map((s) => ({
		label: s.label,
		onclick: () => void newDesign(s.id)
	}));
	const addItems: MenuItem[] = Object.values(KINDS).map((k) => ({
		label: k.label,
		icon: k.icon,
		onclick: () => add(k.make())
	}));
	const designItems = $derived<MenuItem[]>([
		{
			label: 'Set as default',
			icon: Star,
			disabled: !!current?.is_default,
			onclick: () => void setDefault()
		},
		{
			label: 'Delete',
			icon: Trash2,
			danger: true,
			disabled: designs.length <= 1,
			onclick: () => void deleteCurrent()
		}
	]);

	const val = (e: Event) => (e.currentTarget as HTMLInputElement).value;
	const linkLines = (text: string) =>
		text
			.split('\n')
			.map((l) => l.trim())
			.filter(Boolean);
	const iconBtn =
		'rounded-sm p-1 text-muted hover:bg-surface-3 hover:text-text disabled:pointer-events-none disabled:opacity-30';
</script>

<svelte:window onkeydown={onKeydown} />

{#if loading}
	<Spinner label="Loading ticket designs…" />
{:else if !current}
	<p class="text-sm text-muted">No ticket designs could be loaded.</p>
{:else}
	{@const line = selection ? current.elements[selection.index] : undefined}
	<!-- The designs -->
	<div class="mb-5 flex flex-wrap items-center gap-2">
		{#each designs as d (d.id)}
			<button
				type="button"
				aria-pressed={d.id === current.id}
				class="flex h-8 items-center gap-2 border px-3 text-sm font-medium
					{d.id === current.id
					? 'border-accent bg-surface-2 text-text'
					: 'border-border text-muted hover:text-text'}"
				onclick={() => void openDesign(d.id)}
			>
				{d.name}
				{#if d.is_default}<span class="text-[0.7rem] text-warning">Default</span>{/if}
			</button>
		{/each}
		<Menu items={starterItems} label="New design" icon={Plus} size="sm" variant="ghost" />
		<div class="ml-auto flex items-center gap-1.5">
			<button
				type="button"
				class={iconBtn}
				title="Undo"
				aria-label="Undo"
				disabled={!canUndo}
				onclick={undo}
			>
				<Undo2 size={15} />
			</button>
			<button
				type="button"
				class={iconBtn}
				title="Redo"
				aria-label="Redo"
				disabled={!canRedo}
				onclick={redo}
			>
				<Redo2 size={15} />
			</button>
			<Button size="sm" onclick={() => void duplicate()}><Copy size={13} /> Duplicate</Button>
			<Menu items={designItems} icon={Ellipsis} size="sm" ariaLabel="More design actions" />
		</div>
	</div>

	<div class="grid gap-6 lg:grid-cols-[auto_minmax(0,1fr)]">
		<!-- The ticket -->
		<div class="flex flex-col gap-2.5 self-start">
			<div class="flex items-center gap-1.5">
				<Menu items={addItems} label="Add a line" icon={Plus} size="sm" />
				<Button
					size="sm"
					class="ml-auto"
					disabled={printing}
					title="Print this design with the sample details shown"
					onclick={() => void testPrint()}
				>
					<Printer size={13} />
					{printing ? 'Printing…' : 'Test print'}
				</Button>
			</div>
			{#if !previewImage}
				<Spinner size="sm" label="Rendering preview…" />
			{:else}
				<Receipt
					preview={previewImage}
					{selection}
					onselect={(s) => (selection = s)}
					onmove={move}
				/>
			{/if}
			<p class="text-center text-xs text-muted">Click a line to edit it, drag it to move it.</p>
		</div>

		<div class="min-w-0 space-y-4">
			<!-- The selected line -->
			{#if line && selection}
				{@const index = selection.index}
				<section class="space-y-4 border border-border bg-surface-1 p-4">
					<div class="flex items-center gap-1">
						<h3 class="mr-auto text-sm font-medium">{kindOf(line).label}</h3>
						<span class="mr-1 text-xs text-muted"
							>Line {index + 1} of {current.elements.length}</span
						>
						<button
							type="button"
							class={iconBtn}
							aria-label="Move up"
							disabled={index === 0}
							onclick={() => move(index, index - 1)}><ChevronUp size={15} /></button
						>
						<button
							type="button"
							class={iconBtn}
							aria-label="Move down"
							disabled={index === current.elements.length - 1}
							onclick={() => move(index, index + 1)}><ChevronDown size={15} /></button
						>
						<button
							type="button"
							class="{iconBtn} hover:text-danger"
							aria-label="Remove line"
							onclick={() => remove(index)}><Trash2 size={15} /></button
						>
					</div>

					{#if line.type === 'columns'}
						<ColumnsFields
							el={line}
							cell={selection.cell}
							item={selection.item}
							onselect={(cell, item) => (selection = { index, cell, item })}
							onedit={(mutate, key) => edit((d) => mutate(lineAt(d)), key && `${index}-${key}`)}
						/>
					{:else}
						<ItemFields
							el={line}
							onpatch={(key, value) =>
								edit((d) => {
									setField(lineAt(d), key, value);
								}, `${index}-${key}`)}
						/>
					{/if}
				</section>
			{:else}
				<p class="border border-border bg-surface-1 p-4 text-sm text-muted">
					This design has no lines yet. Add one under the ticket.
				</p>
			{/if}

			<!-- This design -->
			<section class="space-y-4 border border-border bg-surface-1 p-4">
				<h3 class="text-sm font-medium">This design</h3>
				<div class="grid gap-4 sm:grid-cols-2">
					<Field label="Name" forId="td-name">
						<Input
							id="td-name"
							value={current.name}
							oninput={(e) => edit((d) => (d.name = val(e)), 'name')}
							placeholder="Design name"
						/>
					</Field>
					<Field label="Columns font" forId="td-font">
						<Select
							id="td-font"
							value={current.font}
							onchange={(e) => edit((d) => (d.font = val(e)))}
						>
							{#each FONTS as f (f.id)}
								<option value={f.id}>{f.label}{f.hint ? ` (${f.hint.toLowerCase()})` : ''}</option>
							{/each}
						</Select>
					</Field>
					<Field label="Date" forId="td-date">
						<Select
							id="td-date"
							value={current.date_format}
							onchange={(e) => edit((d) => (d.date_format = val(e)))}
						>
							{#each DATE_FORMATS as f (f.id)}<option value={f.id}>{f.label}</option>{/each}
						</Select>
					</Field>
					<Field label="Time" forId="td-time">
						<Select
							id="td-time"
							value={current.time_format}
							onchange={(e) => edit((d) => (d.time_format = val(e)))}
						>
							{#each TIME_FORMATS as f (f.id)}<option value={f.id}>{f.label}</option>{/each}
						</Select>
					</Field>
				</div>
				<Disclosure
					title="Surprise links"
					note={current.qr_links.length ? `${current.qr_links.length}` : undefined}
				>
					<Field label="One link per line" forId="td-links">
						<textarea
							id="td-links"
							rows="4"
							class="w-full rounded-md border border-border bg-surface-2 px-3 py-2 font-mono text-sm text-text hover:border-border-strong focus:border-accent focus:outline-none"
							placeholder="https://…"
							value={current.qr_links.join('\n')}
							onchange={(e) => edit((d) => (d.qr_links = linkLines(val(e))))}></textarea>
					</Field>
					<p class="mt-1.5 text-xs text-muted">
						A QR code set to "A surprise link" prints one of these at random. Up to 50 http(s)
						links; with none, it prints nothing.
					</p>
				</Disclosure>
			</section>

			<p class="text-xs text-muted">
				Saved as you go. A programme picks its design in its box-office panel.
			</p>
		</div>
	</div>
{/if}
