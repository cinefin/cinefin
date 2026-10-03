<script lang="ts">
	// One design's page: click a line on the receipt to edit it beside it (drag to reorder), and set
	// the design's own settings below. Everything saves as you go, with undo.
	import {
		ChevronDown,
		ChevronUp,
		Copy,
		Ellipsis,
		Plus,
		Printer,
		Redo2,
		Trash2,
		Undo2
	} from '@lucide/svelte';
	import { untrack } from 'svelte';
	import { goto } from '$app/navigation';
	import { base } from '$app/paths';
	import { api, unwrap } from '$lib/api/client';
	import { attempt, raw } from '$lib/settings/form.svelte';
	import { showToast } from '$lib/toast.svelte';
	import Field from '$lib/settings/Field.svelte';
	import PageHeader from '$lib/components/shell/PageHeader.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Menu, { type MenuItem } from '$lib/components/ui/Menu.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import Switch from '$lib/components/ui/Switch.svelte';
	import type ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import ColumnsFields from '$lib/tickets/ColumnsFields.svelte';
	import IconButton from '$lib/tickets/IconButton.svelte';
	import ItemFields from '$lib/tickets/ItemFields.svelte';
	import Receipt from '$lib/tickets/Receipt.svelte';
	import { History } from '$lib/tickets/history';
	import {
		DATE_FORMATS,
		FONTS,
		KINDS,
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
	import SettingList from './SettingList.svelte';
	import SettingRow from './SettingRow.svelte';

	let { id, confirm }: { id: number; confirm: ConfirmDialog['confirm'] } = $props();
	type Summary = Pick<Design, 'id' | 'name' | 'is_default'>;

	const TICKETS = `${base}/settings?tab=tickets`;

	let designs = $state<Summary[]>([]);
	let current = $state<Design | null>(null);
	let selection = $state<Selection | null>(null);
	let loading = $state(true);
	// An edit not yet sent: flushed when the page switches design or is left.
	let dirty = false;

	const history = new History<DesignDraft>();
	let canUndo = $state(false);
	let canRedo = $state(false);

	function debounced(fn: () => unknown, ms: number) {
		let pending: ReturnType<typeof setTimeout> | undefined;
		const run = () => {
			clearTimeout(pending);
			pending = setTimeout(fn, ms);
		};
		run.cancel = () => clearTimeout(pending);
		return run;
	}
	const scheduleSave = debounced(() => save(), 500);
	const schedulePreview = debounced(() => preview(), 300);

	function flush() {
		scheduleSave.cancel();
		if (dirty) void save();
	}

	$effect(() => {
		void loadDesigns();
		return () => {
			schedulePreview.cancel();
			flush();
		};
	});
	// The route reuses this page for another design (after Duplicate): open it.
	$effect(() => {
		const want = id;
		untrack(() => {
			flush();
			void openDesign(want).then(() => (loading = false));
		});
	});

	async function loadDesigns() {
		try {
			designs = await raw(api.GET('/api/v2/tickets/designs'));
		} catch {
			// Supplementary: only Delete's guard and the default's name read it.
		}
	}

	async function openDesign(designId: number) {
		try {
			current = (await raw(
				api.GET('/api/v2/tickets/designs/{design_id}', {
					params: { path: { design_id: designId } }
				})
			)) as Design;
		} catch {
			current = null;
			return;
		}
		selection = current.elements.length ? { index: 0 } : null;
		history.reset(draft());
		syncHistory();
		schedulePreview();
	}

	function draft(): DesignDraft {
		const { name, elements, date_format, time_format, qr_links, font } = $state.snapshot(current!);
		return { name, elements, date_format, time_format, qr_links, font };
	}

	/** The draft without its name, as the API takes it (kinds.ts checks the elements fit). */
	function apiFields() {
		const { name: _name, ...fields } = draft();
		return { ...fields, elements: fields.elements as Element[] };
	}

	function syncHistory() {
		canUndo = history.canUndo;
		canRedo = history.canRedo;
	}

	function changed() {
		dirty = true;
		syncHistory();
		scheduleSave();
		schedulePreview();
	}

	/** Apply `mutate` to the design; `key` merges a burst of edits to one field into one undo step. */
	function edit(mutate: (design: Design) => void, key = '') {
		if (!current) return;
		mutate(current);
		history.record(draft(), key);
		changed();
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
		changed();
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

	async function save() {
		if (!current) return;
		dirty = false;
		const name = current.name;
		const design_id = current.id;
		const fields = apiFields();
		await attempt(async () => {
			await raw(
				api.PUT('/api/v2/tickets/designs/{design_id}', {
					params: { path: { design_id } },
					body: { name: name.trim() || 'Untitled', ...fields }
				})
			);
		}, 'Failed to save design');
	}

	let previewImage = $state<Preview | null>(null);

	async function preview() {
		if (!current) return;
		try {
			const data = await raw(
				api.POST('/api/v2/tickets/preview', { body: { design: apiFields() } })
			);
			previewImage = data.data;
		} catch {
			// Supplementary: keep the last good one.
		}
	}

	let printing = $state(false);
	async function testPrint() {
		if (!current) return;
		printing = true;
		await attempt(async () => {
			const data = await unwrap(
				api.POST('/api/v2/tickets/test', { body: { include_seat: true, design: apiFields() } })
			);
			showToast(`Test ticket printed${data.seat ? ` (seat ${data.seat})` : ''}`, 'success');
		}, 'Failed to print test ticket');
		printing = false;
	}

	function duplicate() {
		if (!current) return;
		const design_id = current.id;
		void attempt(async () => {
			const copy = await raw(
				api.POST('/api/v2/tickets/designs/{design_id}/duplicate', {
					params: { path: { design_id } }
				})
			);
			await loadDesigns();
			await goto(`${base}/settings/tickets/${copy.id}`);
		}, 'Could not duplicate');
	}

	async function setDefault() {
		if (!current) return;
		const design = current;
		await attempt(async () => {
			await raw(
				api.PUT('/api/v2/tickets/designs/{design_id}', {
					params: { path: { design_id: design.id } },
					body: { is_default: true }
				})
			);
			design.is_default = true;
			await loadDesigns();
		}, 'Could not set default');
	}

	async function deleteCurrent() {
		if (!current || designs.length <= 1) return;
		if (!(await confirm(`Delete design "${current.name}"?`, { confirmLabel: 'Delete' }))) return;
		const design_id = current.id;
		await attempt(async () => {
			await raw(
				api.DELETE('/api/v2/tickets/designs/{design_id}', { params: { path: { design_id } } })
			);
			dirty = false;
			current = null;
			await goto(TICKETS);
		}, 'Could not delete');
	}

	const addItems: MenuItem[] = Object.values(KINDS).map((k) => ({
		label: k.label,
		icon: k.icon,
		onclick: () => add(k.make())
	}));
	const designItems = $derived<MenuItem[]>([
		{
			label: 'Delete design',
			icon: Trash2,
			danger: true,
			disabled: designs.length <= 1,
			onclick: deleteCurrent
		}
	]);

	const val = (e: Event) => (e.currentTarget as HTMLInputElement).value;
	const labelOf = (choices: { id: string; label: string }[], value: string) =>
		choices.find((c) => c.id === value)?.label ?? value;
	const linkLines = (text: string) =>
		text
			.split('\n')
			.map((l) => l.trim())
			.filter(Boolean);
	const defaultName = $derived(designs.find((d) => d.is_default)?.name ?? 'the default');
</script>

<svelte:window onkeydown={onKeydown} />

<PageHeader
	title={current?.name || 'Ticket design'}
	count={current?.is_default ? 'Default' : undefined}
	back={{ href: TICKETS, label: 'Settings' }}
	actions={current ? headerActions : undefined}
/>
{#snippet headerActions()}
	<Button size="sm" onclick={duplicate}><Copy size={13} /> Duplicate</Button>
	<Menu items={designItems} icon={Ellipsis} size="sm" ariaLabel="More design actions" />
{/snippet}

{#if loading}
	<Spinner label="Loading the design…" />
{:else if !current}
	<p class="text-sm text-muted">
		This design could not be loaded. <a class="text-accent hover:underline" href={TICKETS}
			>Back to ticket settings</a
		>.
	</p>
{:else}
	{@const line = selection ? current.elements[selection.index] : undefined}
	<div class="space-y-6 pb-8">
		<section class="border border-border bg-surface-1">
			<div class="flex flex-wrap items-center gap-1.5 border-b border-border px-3 py-2">
				<Menu items={addItems} label="Add a line" icon={Plus} size="sm" />
				<Button
					size="sm"
					disabled={printing}
					title="Print this design with the sample details shown"
					onclick={() => void testPrint()}
				>
					<Printer size={13} />
					{printing ? 'Printing…' : 'Test print'}
				</Button>
				<span class="ml-auto"></span>
				<IconButton icon={Undo2} label="Undo" title="Undo" disabled={!canUndo} onclick={undo} />
				<IconButton icon={Redo2} label="Redo" title="Redo" disabled={!canRedo} onclick={redo} />
			</div>

			<div class="grid gap-6 p-4 lg:grid-cols-[auto_minmax(0,1fr)]">
				<div class="flex flex-col gap-2.5 self-start">
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

				<div class="min-w-0">
					{#if line && selection}
						{@const index = selection.index}
						<section class="space-y-4 border border-border bg-surface-2/40 p-4">
							<div class="flex items-center gap-1">
								<h3 class="mr-auto text-sm font-medium">{kindOf(line).label}</h3>
								<span class="mr-1 text-xs text-muted"
									>Line {index + 1} of {current.elements.length}</span
								>
								<IconButton
									icon={ChevronUp}
									label="Move up"
									disabled={index === 0}
									onclick={() => move(index, index - 1)}
								/>
								<IconButton
									icon={ChevronDown}
									label="Move down"
									disabled={index === current.elements.length - 1}
									onclick={() => move(index, index + 1)}
								/>
								<IconButton
									icon={Trash2}
									label="Remove line"
									danger
									onclick={() => remove(index)}
								/>
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
										edit((d) => setField(lineAt(d), key, value), `${index}-${key}`)}
								/>
							{/if}
						</section>
					{:else}
						<p class="border border-border bg-surface-2/40 p-4 text-sm text-muted">
							This design has no lines yet. Add one from the toolbar.
						</p>
					{/if}
				</div>
			</div>
		</section>

		<SettingList
			title="This design"
			text="Saved as you go. A programme picks its design in its box-office panel"
		>
			<SettingRow label="Name" summary={current.name}>
				<div class="max-w-sm">
					<Field label="Name" forId="td-name">
						<Input
							id="td-name"
							value={current.name}
							oninput={(e) => edit((d) => (d.name = val(e)), 'name')}
							placeholder="Design name"
						/>
					</Field>
				</div>
			</SettingRow>
			<SettingRow
				label="Date and time"
				hint="How {'{date}'} and {'{time}'} print"
				mono
				summary="{labelOf(DATE_FORMATS, current.date_format)} · {labelOf(
					TIME_FORMATS,
					current.time_format
				)}"
			>
				<div class="grid max-w-md gap-4 sm:grid-cols-2">
					<Field label="Date" forId="td-date">
						<Select
							id="td-date"
							value={current.date_format}
							onchange={(e) => edit((d) => (d.date_format = val(e)))}
						>
							{#each DATE_FORMATS as o (o.id)}<option value={o.id}>{o.label}</option>{/each}
						</Select>
					</Field>
					<Field label="Time" forId="td-time">
						<Select
							id="td-time"
							value={current.time_format}
							onchange={(e) => edit((d) => (d.time_format = val(e)))}
						>
							{#each TIME_FORMATS as o (o.id)}<option value={o.id}>{o.label}</option>{/each}
						</Select>
					</Field>
				</div>
			</SettingRow>
			<SettingRow
				label="Columns font"
				hint="For lines set side by side"
				summary={labelOf(FONTS, current.font)}
			>
				<div class="max-w-sm">
					<Field label="Columns font" forId="td-font">
						<Select
							id="td-font"
							value={current.font}
							onchange={(e) => edit((d) => (d.font = val(e)))}
						>
							{#each FONTS as o (o.id)}
								<option value={o.id}>{o.label}{o.hint ? ` (${o.hint.toLowerCase()})` : ''}</option>
							{/each}
						</Select>
					</Field>
				</div>
			</SettingRow>
			<SettingRow
				label="Surprise links"
				hint="For a QR code set to a surprise"
				summary={current.qr_links.length
					? `${current.qr_links.length} link${current.qr_links.length === 1 ? '' : 's'}, one picked at random`
					: 'None: a surprise QR code prints nothing'}
			>
				<div class="max-w-xl">
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
						links.
					</p>
				</div>
			</SettingRow>
			<SettingRow
				label="Default design"
				hint="For programmes without their own"
				summary={current.is_default
					? 'This is the default'
					: `Programmes without their own use ${defaultName}`}
			>
				{#snippet control()}
					<Switch
						label=""
						ariaLabel="Default design"
						checked={current?.is_default ?? false}
						disabled={current?.is_default}
						onchange={(on) => on && void setDefault()}
					/>
				{/snippet}
			</SettingRow>
		</SettingList>
	</div>
{/if}
