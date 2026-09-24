<script lang="ts">
	import { Image, Plug, Plus, Receipt, RotateCcw, Trash2, Upload, X } from '@lucide/svelte';
	import { api, unwrap } from '$lib/api/client';
	import { mutate } from '$lib/api/mutate';
	import { raw, type SettingsStore } from '$lib/settings/form.svelte';
	import { showToast } from '$lib/toast.svelte';
	import { uploadWithProgress } from '$lib/upload';
	import type { components } from '$lib/api/types.gen';
	import type { CheckState } from '$lib/settings/types';

	type TicketImage = components['schemas']['TicketImageSchema'];
	import Button from '$lib/components/ui/Button.svelte';
	import Tabs from '$lib/components/ui/Tabs.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import CheckResult from './CheckResult.svelte';
	import Field from './Field.svelte';
	import TicketDesigner from './TicketDesigner.svelte';
	import type ConfirmDialog from '$lib/components/ConfirmDialog.svelte';

	interface Props {
		store: SettingsStore;
		confirm: ConfirmDialog['confirm'];
	}
	let { store, confirm }: Props = $props();

	type Tab = 'boxoffice' | 'printer' | 'designs';
	let tab = $state<Tab>('boxoffice');
	const TABS: { id: Tab; label: string }[] = [
		{ id: 'boxoffice', label: 'Box office' },
		{ id: 'printer', label: 'Printer' },
		{ id: 'designs', label: 'Designs' }
	];

	const totalSeats = $derived(
		(parseInt(store.main.ticket_total_rows, 10) || 0) *
			(parseInt(store.main.ticket_seats_per_row, 10) || 0)
	);

	let images = $state<TicketImage[]>([]);
	let imageInput: HTMLInputElement | undefined = $state();
	let imageUploading = $state(false);

	$effect(() => {
		void loadImages();
	});

	async function loadImages() {
		try {
			images = await raw(api.GET('/api/v2/tickets/images'));
		} catch {
			// Supplementary — the grid just stays empty.
		}
	}

	async function onImagePicked() {
		const file = imageInput?.files?.[0];
		if (!file) return;
		imageUploading = true;
		try {
			await uploadWithProgress('/api/v2/tickets/images/upload', file, {}, undefined, 'image');
			await loadImages();
			showToast('Image added', 'success');
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Image upload failed', 'error');
		} finally {
			imageUploading = false;
			if (imageInput) imageInput.value = '';
		}
	}

	async function deleteImage(img: TicketImage) {
		const ok = await confirm(
			`Delete "${img.name}"? Ticket designs still using it will skip the image when printing.`,
			{ confirmLabel: 'Delete' }
		);
		if (!ok) return;
		try {
			await raw(api.DELETE('/api/v2/tickets/images', { params: { query: { name: img.name } } }));
			await loadImages();
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Could not delete image', 'error');
		}
	}

	let printerResult = $state<CheckState>(null);
	let printerBusy = $state(false);

	async function checkPrinter() {
		printerBusy = true;
		printerResult = { state: 'pending', message: 'Testing…' };
		try {
			const res = await raw(
				api.POST('/api/v2/settings/test-printer/', {
					body: {
						printer_type: store.main.ticket_printer_type,
						device: store.main.ticket_printer_device.trim() || null,
						host: store.main.ticket_printer_host.trim() || null,
						port: parseInt(store.main.ticket_printer_port, 10) || null
					}
				})
			);
			printerResult = { state: res.ok ? 'ok' : 'error', message: res.message };
		} catch (e) {
			printerResult = { state: 'error', message: e instanceof Error ? e.message : 'Test failed' };
		} finally {
			printerBusy = false;
		}
	}

	async function testPrint() {
		printerBusy = true;
		try {
			const data = await unwrap(api.POST('/api/v2/tickets/test', { body: { include_seat: true } }));
			showToast(`Test ticket printed${data.seat ? ` (seat ${data.seat})` : ''}`, 'success');
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Failed to print test ticket', 'error');
		} finally {
			printerBusy = false;
		}
	}

	// Reset acts on the *saved* config, not the unsaved form values.
	async function resetPrinter() {
		printerBusy = true;
		printerResult = { state: 'pending', message: 'Resetting…' };
		try {
			const msg = await mutate(api.POST('/api/v2/tickets/reset'));
			printerResult = { state: 'ok', message: msg || 'Printer reset' };
		} catch (e) {
			printerResult = { state: 'error', message: e instanceof Error ? e.message : 'Reset failed' };
		} finally {
			printerBusy = false;
		}
	}

	function addQrLink() {
		store.main.ticket_qr_fun_links = [...store.main.ticket_qr_fun_links, ''];
	}
	function removeQrLink(i: number) {
		store.main.ticket_qr_fun_links = store.main.ticket_qr_fun_links.filter((_, x) => x !== i);
	}
</script>

<div class="space-y-4">
	<Tabs
		tabs={TABS}
		value={tab}
		onselect={(id) => (tab = id as typeof tab)}
		label="Ticket sections"
	/>

	{#if tab === 'boxoffice'}
		<Card title="Auditorium">
			<div class="grid max-w-xl gap-4 sm:grid-cols-3">
				<Field
					label="Rows"
					forId="set-rows"
					hint="Lettered A-Z, max 26."
					dirty={store.isDirty('ticket_total_rows')}
					error={store.errorFor('ticket_total_rows')}
				>
					<Input id="set-rows" type="number" bind:value={store.main.ticket_total_rows} />
				</Field>
				<Field
					label="Seats per row"
					forId="set-seats"
					dirty={store.isDirty('ticket_seats_per_row')}
					error={store.errorFor('ticket_seats_per_row')}
				>
					<Input id="set-seats" type="number" bind:value={store.main.ticket_seats_per_row} />
				</Field>
				<Field label="Total seats">
					<div class="flex h-9 items-center font-mono text-lg">{totalSeats.toLocaleString()}</div>
				</Field>
			</div>
		</Card>

		<Card title="Images">
			<Field
				label="Image library"
				hint="Extra images any ticket design's image element can print - pick them in the design editor."
			>
				<div class="flex flex-wrap gap-2">
					{#each images as img (img.name)}
						<div
							class="group relative flex w-28 flex-col items-center gap-1 rounded-md border border-border bg-surface-2 p-2"
						>
							<img src={img.url} alt={img.name} class="h-14 w-full bg-white object-contain" />
							<span class="w-full truncate text-center text-xs text-muted" title={img.name}>
								{img.name}
							</span>
							<button
								type="button"
								class="absolute -top-1.5 -right-1.5 hidden rounded-sm border border-border-strong bg-surface-1 p-0.5 text-muted group-hover:block hover:text-danger"
								title="Delete image"
								aria-label="Delete image {img.name}"
								onclick={() => void deleteImage(img)}
							>
								<Trash2 size={12} />
							</button>
						</div>
					{/each}
					<button
						type="button"
						class="flex h-24 w-28 flex-col items-center justify-center gap-1 rounded-md border border-dashed border-border-strong text-xs text-muted hover:border-accent-dim hover:text-text disabled:opacity-45"
						disabled={imageUploading}
						onclick={() => imageInput?.click()}
					>
						<Upload size={15} />
						{imageUploading ? 'Uploading…' : 'Add image'}
					</button>
				</div>
				<input
					type="file"
					bind:this={imageInput}
					accept="image/png,image/jpeg,image/gif"
					hidden
					onchange={onImagePicked}
				/>
			</Field>
		</Card>

		<Card title="Ticket defaults">
			<div class="grid max-w-xl gap-4 sm:grid-cols-2">
				<Field
					label="Date format"
					forId="set-date-format"
					dirty={store.isDirty('ticket_date_format')}
					error={store.errorFor('ticket_date_format')}
				>
					<Select id="set-date-format" bind:value={store.main.ticket_date_format} class="w-full">
						<option value="%d/%m/%Y">31/12/2026</option>
						<option value="%m/%d/%Y">12/31/2026</option>
						<option value="%Y-%m-%d">2026-12-31</option>
						<option value="%a %d %b %Y">Thu 31 Dec 2026</option>
					</Select>
				</Field>
				<Field
					label="Time format"
					forId="set-time-format"
					hint="Used by the {'{date}'} / {'{time}'} tokens."
					dirty={store.isDirty('ticket_time_format')}
					error={store.errorFor('ticket_time_format')}
				>
					<Select id="set-time-format" bind:value={store.main.ticket_time_format} class="w-full">
						<option value="%H:%M">19:30</option>
						<option value="%I:%M %p">07:30 PM</option>
					</Select>
				</Field>
			</div>

			<div class="mt-4">
				<Field
					label="Surprise QR links"
					hint={'Used by any QR element in "Surprise link" mode - one is picked at random per ticket. http(s) URLs; up to 50.'}
					dirty={store.isDirty('ticket_qr_fun_links')}
					error={store.errorFor('ticket_qr_fun_links')}
				>
					{#if !store.main.ticket_qr_fun_links.length}
						<p class="mb-2 text-sm text-muted">
							No links - surprise QR elements will print nothing
						</p>
					{:else}
						<div class="mb-2 max-w-xl space-y-1.5">
							{#each store.main.ticket_qr_fun_links as _, i (i)}
								<div class="flex items-center gap-2">
									<Input bind:value={store.main.ticket_qr_fun_links[i]} placeholder="https://…" />
									<button
										type="button"
										class="shrink-0 rounded-sm p-1 text-muted hover:bg-surface-3 hover:text-danger"
										title="Remove link"
										aria-label="Remove link"
										onclick={() => removeQrLink(i)}
									>
										<X size={14} />
									</button>
								</div>
							{/each}
						</div>
					{/if}
					<Button size="sm" onclick={addQrLink}><Plus size={13} /> Add link</Button>
				</Field>
			</div>
		</Card>
	{:else if tab === 'printer'}
		<Card title="Printer">
			<div class="grid max-w-xl gap-4 sm:grid-cols-2">
				<Field
					label="Printer connection"
					forId="set-printer-type"
					dirty={store.isDirty('ticket_printer_type')}
					error={store.errorFor('ticket_printer_type')}
				>
					<Select id="set-printer-type" bind:value={store.main.ticket_printer_type} class="w-full">
						<option value="file">Local device file</option>
						<option value="network">Network (ESC/POS over TCP)</option>
					</Select>
				</Field>
				<Field
					label="Paper width"
					forId="set-paper-width"
					hint="Selects the printer profile and caps printed image widths."
					dirty={store.isDirty('ticket_paper_width')}
					error={store.errorFor('ticket_paper_width')}
				>
					<Select id="set-paper-width" bind:value={store.main.ticket_paper_width} class="w-full">
						<option value="384">58 mm paper (384 dots printable)</option>
						<option value="576">80 mm paper (576 dots printable)</option>
					</Select>
				</Field>
			</div>

			{#if store.main.ticket_printer_type === 'file'}
				<div class="mt-4 max-w-xl">
					<Field
						label="Printer device"
						forId="set-printer-device"
						hint="Device file the thermal printer prints to (ESC/POS). Typically /dev/usb/lp0."
						dirty={store.isDirty('ticket_printer_device')}
						error={store.errorFor('ticket_printer_device')}
					>
						<Input
							id="set-printer-device"
							bind:value={store.main.ticket_printer_device}
							placeholder="/dev/usb/lp0"
						/>
					</Field>
				</div>
			{:else}
				<div class="mt-4 grid max-w-2xl gap-4 sm:grid-cols-3">
					<Field
						label="Printer host"
						forId="set-printer-host"
						hint="Machine the printer is reachable on - e.g. exposed with socat TCP-LISTEN:9100,fork,reuseaddr OPEN:/dev/usb/lp0."
						dirty={store.isDirty('ticket_printer_host')}
						error={store.errorFor('ticket_printer_host')}
					>
						<Input
							id="set-printer-host"
							bind:value={store.main.ticket_printer_host}
							placeholder="10.0.0.20"
						/>
					</Field>
					<Field
						label="Port"
						forId="set-printer-port"
						dirty={store.isDirty('ticket_printer_port')}
						error={store.errorFor('ticket_printer_port')}
					>
						<Input
							id="set-printer-port"
							type="number"
							bind:value={store.main.ticket_printer_port}
						/>
					</Field>
					<Field
						label="Timeout (s)"
						forId="set-printer-timeout"
						hint="How long to wait on a slow printer before giving up mid-write. Raise it if network prints get cut off or come out garbled."
						dirty={store.isDirty('ticket_printer_timeout')}
						error={store.errorFor('ticket_printer_timeout')}
					>
						<Input
							id="set-printer-timeout"
							type="number"
							bind:value={store.main.ticket_printer_timeout}
							placeholder="30"
						/>
					</Field>
				</div>
			{/if}

			<div class="mt-4 grid max-w-xl gap-4 sm:grid-cols-2">
				<Field
					label="Image mode"
					forId="set-image-mode"
					hint="How the logo & rating images are sent. If tickets print garbage, try a different mode - or Off to rule images out entirely."
					dirty={store.isDirty('ticket_image_mode')}
					error={store.errorFor('ticket_image_mode')}
				>
					<Select id="set-image-mode" bind:value={store.main.ticket_image_mode} class="w-full">
						<option value="raster">Raster (GS v 0) - most compatible</option>
						<option value="column">Column (ESC *)</option>
						<option value="graphics">Graphics (GS ( L)</option>
						<option value="off">Off - text only (no logo/rating)</option>
					</Select>
				</Field>
				<Field
					label="Bottom padding"
					forId="set-feed-lines"
					hint="Blank lines fed after each ticket, so there's slack to tear off. 0-20."
					dirty={store.isDirty('ticket_feed_lines')}
					error={store.errorFor('ticket_feed_lines')}
				>
					<Input
						id="set-feed-lines"
						type="number"
						bind:value={store.main.ticket_feed_lines}
						placeholder="2"
					/>
				</Field>
			</div>

			<div class="mt-5 space-y-2">
				<div class="flex flex-wrap items-center gap-2">
					<Button disabled={printerBusy} onclick={checkPrinter}>
						<Plug size={14} /> Check printer
					</Button>
					<Button disabled={printerBusy} onclick={testPrint}>
						<Receipt size={14} /> Test print
					</Button>
					<Button
						disabled={printerBusy}
						title="Send a reset (ESC @) to unstick a printer that's spitting garbage after a failed print"
						onclick={resetPrinter}
					>
						<RotateCcw size={14} /> Reset printer
					</Button>
				</div>
				<CheckResult result={printerResult} />
				<p class="text-xs text-faint">
					<strong>Check</strong> probes the connection without printing ·
					<strong>Test print</strong> sends a real ticket · <strong>Reset</strong> clears a printer stuck
					after a garbled print (no power-cycle).
				</p>
			</div>
		</Card>
	{:else}
		<Card title="Ticket design">
			<TicketDesigner {confirm} />
		</Card>
	{/if}
</div>
