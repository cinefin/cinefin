<script lang="ts">
	import { ChevronRight, Plug, Printer, Receipt, RotateCcw } from '@lucide/svelte';
	import { api, unwrap } from '$lib/api/client';
	import { mutate } from '$lib/api/mutate';
	import { raw, type SettingsStore } from '$lib/settings/form.svelte';
	import { showToast } from '$lib/toast.svelte';
	import type { CheckState } from '$lib/settings/types';

	import Button from '$lib/components/ui/Button.svelte';
	import Tabs from '$lib/components/ui/Tabs.svelte';
	import StatusLamp from '$lib/components/StatusLamp.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import CheckResult from './CheckResult.svelte';
	import Field from './Field.svelte';
	import TicketDesigner from './TicketDesigner.svelte';
	import type ConfirmDialog from '$lib/components/ConfirmDialog.svelte';

	// The Designs tab auto-saves; the page hides its Save bar there (bind `tab`).
	interface Props {
		store: SettingsStore;
		confirm: ConfirmDialog['confirm'];
		tab?: 'designs' | 'printer';
	}
	let { store, confirm, tab = $bindable('designs') }: Props = $props();

	const TABS = [
		{ id: 'designs', label: 'Designs' },
		{ id: 'printer', label: 'Printer' }
	];

	let printerResult = $state<CheckState>(null);
	let printerBusy = $state(false);
	let checkedAt = $state<Date | null>(null);
	let showQuality = $state(false);

	// The status card at the top of the Printer tab, from the last check.
	const isNetwork = $derived(store.main.ticket_printer_type === 'network');
	const printerStatus = $derived.by(() => {
		if (!printerResult)
			return { colour: 'neutral' as const, label: 'Not checked yet', pending: false };
		if (printerResult.state === 'pending')
			return { colour: 'neutral' as const, label: 'Checking…', pending: true };
		if (printerResult.state === 'ok')
			return { colour: 'green' as const, label: 'Ready', pending: false };
		return { colour: 'red' as const, label: 'Not reachable', pending: false };
	});
	const printerSummary = $derived(
		[
			isNetwork
				? `Network · ${store.main.ticket_printer_host || 'no host'}:${store.main.ticket_printer_port || '9100'}`
				: `USB · ${store.main.ticket_printer_device || 'no device'}`,
			store.main.ticket_paper_width === '576' ? '80 mm' : '58 mm',
			checkedAt
				? `checked ${checkedAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
				: null
		]
			.filter(Boolean)
			.join(' · ')
	);
	const qualitySummary = $derived(
		[
			{
				raster: 'Raster images',
				column: 'Column images',
				graphics: 'Graphics images',
				off: 'No images'
			}[store.main.ticket_image_mode as string] ?? 'Images',
			`${store.main.ticket_feed_lines || 0} blank lines after each ticket`
		].join(' · ')
	);

	// Check once when the Printer tab opens, so the status card has something to say.
	let autoChecked = false;
	$effect(() => {
		if (tab === 'printer' && !autoChecked) {
			autoChecked = true;
			void checkPrinter();
		}
	});

	async function checkPrinter() {
		printerBusy = true;
		printerResult = { state: 'pending', message: 'Checking…' };
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
			checkedAt = new Date();
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
	let resetResult = $state<CheckState>(null);
	async function resetPrinter() {
		printerBusy = true;
		resetResult = { state: 'pending', message: 'Resetting…' };
		try {
			const msg = await mutate(api.POST('/api/v2/tickets/reset'));
			resetResult = { state: 'ok', message: msg || 'Printer reset' };
		} catch (e) {
			resetResult = { state: 'error', message: e instanceof Error ? e.message : 'Reset failed' };
		} finally {
			printerBusy = false;
		}
	}
</script>

<div class="space-y-4">
	<Tabs
		tabs={TABS}
		value={tab}
		onselect={(id) => (tab = id as typeof tab)}
		label="Ticket sections"
	/>

	{#if tab === 'printer'}
		<div class="space-y-4">
			<!-- ── Status ──────────────────────────────────────────────────── -->
			<section class="flex flex-wrap items-center gap-4 border border-border bg-surface-1 p-4">
				<Printer size={26} class="shrink-0 text-muted" />
				<div class="min-w-0 flex-1">
					<StatusLamp colour={printerStatus.colour} pending={printerStatus.pending}>
						<span class="text-base font-medium text-text">{printerStatus.label}</span>
					</StatusLamp>
					<p class="mt-1 font-mono text-xs break-all text-muted">{printerSummary}</p>
					{#if printerResult?.state === 'error'}
						<p class="mt-1 text-xs text-danger">{printerResult.message}</p>
					{/if}
				</div>
				<Button disabled={printerBusy} onclick={checkPrinter}><Plug size={14} /> Check</Button>
				<Button variant="primary" disabled={printerBusy} onclick={testPrint}>
					<Receipt size={14} /> Print a test ticket
				</Button>
			</section>

			<!-- ── Connection ──────────────────────────────────────────────── -->
			<section class="space-y-4 border border-border bg-surface-1 p-4">
				<h3 class="text-sm font-medium">Connection</h3>
				<div>
					<span class="mb-1.5 block text-xs font-medium text-muted">Connected by</span>
					<div class="seg" role="group" aria-label="Connected by">
						<button
							type="button"
							aria-pressed={!isNetwork}
							onclick={() => (store.main.ticket_printer_type = 'file')}>USB cable</button
						>
						<button
							type="button"
							aria-pressed={isNetwork}
							onclick={() => (store.main.ticket_printer_type = 'network')}>Network</button
						>
					</div>
				</div>
				<div class="grid max-w-2xl gap-4 sm:grid-cols-2">
					{#if isNetwork}
						<div class="grid grid-cols-[minmax(0,1fr)_6rem] gap-3">
							<Field
								label="Host"
								forId="set-printer-host"
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
						</div>
					{:else}
						<Field
							label="Device"
							forId="set-printer-device"
							dirty={store.isDirty('ticket_printer_device')}
							error={store.errorFor('ticket_printer_device')}
						>
							<Input
								id="set-printer-device"
								bind:value={store.main.ticket_printer_device}
								placeholder="/dev/usb/lp0"
								class="font-mono"
							/>
						</Field>
					{/if}
					<Field
						label="Paper"
						forId="set-paper-width"
						dirty={store.isDirty('ticket_paper_width')}
						error={store.errorFor('ticket_paper_width')}
					>
						<Select id="set-paper-width" bind:value={store.main.ticket_paper_width} class="w-full">
							<option value="384">58 mm roll</option>
							<option value="576">80 mm roll</option>
						</Select>
					</Field>
				</div>
				{#if isNetwork}
					<p class="text-xs text-muted">
						A printer on another machine can be shared with, for example,
						<code class="font-mono">socat TCP-LISTEN:9100,fork,reuseaddr OPEN:/dev/usb/lp0</code>.
					</p>
				{/if}
			</section>

			<!-- ── Print quality ───────────────────────────────────────────── -->
			<section class="border border-border bg-surface-1">
				<button
					type="button"
					class="flex w-full items-center gap-2 px-4 py-3 text-left text-sm font-medium hover:bg-surface-2"
					aria-expanded={showQuality}
					onclick={() => (showQuality = !showQuality)}
				>
					<ChevronRight size={14} class="transition-transform {showQuality ? 'rotate-90' : ''}" />
					Print quality
					<span class="ml-auto text-xs font-normal text-muted">{qualitySummary}</span>
				</button>
				{#if showQuality}
					<div class="grid max-w-2xl gap-4 px-4 pb-4 sm:grid-cols-2">
						<Field
							label="Images"
							forId="set-image-mode"
							hint="Tickets printing garbage? Try another mode, or No images."
							dirty={store.isDirty('ticket_image_mode')}
							error={store.errorFor('ticket_image_mode')}
						>
							<Select id="set-image-mode" bind:value={store.main.ticket_image_mode} class="w-full">
								<option value="raster">Raster (most printers)</option>
								<option value="column">Column</option>
								<option value="graphics">Graphics</option>
								<option value="off">No images (text only)</option>
							</Select>
						</Field>
						<Field
							label="Blank lines after each ticket"
							forId="set-feed-lines"
							hint="Slack to tear off, 0 to 20."
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
						{#if isNetwork}
							<Field
								label="Timeout (s)"
								forId="set-printer-timeout"
								hint="Raise it if network prints get cut off."
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
						{/if}
					</div>
				{/if}
			</section>

			<!-- ── Reset ───────────────────────────────────────────────────── -->
			<section class="flex flex-wrap items-center gap-3 border-t border-border pt-4">
				<div class="mr-auto">
					<h3 class="text-sm font-medium">Printing garbage?</h3>
					<p class="mt-0.5 text-xs text-muted">
						Reset clears a printer stuck after a garbled print, without a power cycle.
					</p>
				</div>
				<Button disabled={printerBusy} onclick={resetPrinter}>
					<RotateCcw size={14} /> Reset printer
				</Button>
			</section>
			<CheckResult result={resetResult} />
		</div>
	{:else}
		<TicketDesigner {store} {confirm} />
	{/if}
</div>

<style>
	.seg {
		display: inline-flex;
		border: 1px solid var(--color-border-strong);
	}
	.seg button {
		height: 2.1rem;
		padding: 0 0.9rem;
		border-right: 1px solid var(--color-border-strong);
		color: var(--color-muted);
		font-size: 0.85rem;
		font-weight: 500;
	}
	.seg button:last-child {
		border-right: 0;
	}
	.seg button:hover {
		color: var(--color-text);
	}
	.seg button[aria-pressed='true'] {
		background: var(--color-surface-3);
		color: var(--color-text);
	}
</style>
