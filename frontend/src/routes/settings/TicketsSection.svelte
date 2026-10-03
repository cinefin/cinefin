<script lang="ts">
	import { ChevronRight, Plug, Printer, Receipt, RotateCcw } from '@lucide/svelte';
	import { api, unwrap } from '$lib/api/client';
	import { mutate } from '$lib/api/mutate';
	import { attempt, errorText, raw, runCheck, type SettingsStore } from '$lib/settings/form.svelte';
	import { showToast } from '$lib/toast.svelte';
	import type { CheckState } from '$lib/settings/types';
	import Button from '$lib/components/ui/Button.svelte';
	import Tabs from '$lib/components/ui/Tabs.svelte';
	import StatusLamp from '$lib/components/StatusLamp.svelte';
	import CheckResult from './CheckResult.svelte';
	import StoreField, { storeField } from '$lib/settings/StoreField.svelte';
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

	const HOST = storeField('ticket_printer_host', 'Host', 'set-printer-host', {
		placeholder: '10.0.0.20'
	});
	const PORT = storeField('ticket_printer_port', 'Port', 'set-printer-port', { type: 'number' });
	const DEVICE = storeField('ticket_printer_device', 'Device', 'set-printer-device', {
		placeholder: '/dev/usb/lp0',
		input: 'font-mono'
	});
	const PAPER = storeField('ticket_paper_width', 'Paper', 'set-paper-width', {
		input: 'w-full',
		options: [
			['384', '58 mm roll'],
			['576', '80 mm roll']
		]
	});
	const QUALITY = [
		storeField('ticket_image_mode', 'Images', 'set-image-mode', {
			hint: 'Tickets printing garbage? Try another mode, or No images.',
			input: 'w-full',
			options: [
				['raster', 'Raster (most printers)'],
				['column', 'Column'],
				['graphics', 'Graphics'],
				['off', 'No images (text only)']
			]
		}),
		storeField('ticket_feed_lines', 'Blank lines after each ticket', 'set-feed-lines', {
			hint: 'Slack to tear off, 0 to 20.',
			type: 'number',
			placeholder: '2'
		}),
		storeField('ticket_cut', 'Cut after each ticket', 'set-cut', {
			hint: 'Needs a printer with a cutter. Partial leaves a tab to tear.',
			input: 'w-full',
			options: [
				['off', 'Off'],
				['partial', 'Partial cut'],
				['full', 'Full cut']
			]
		}),
		storeField('ticket_printer_timeout', 'Timeout (s)', 'set-printer-timeout', {
			hint: 'Raise it if network prints get cut off.',
			type: 'number',
			placeholder: '30'
		})
	];

	let printerResult = $state<CheckState>(null);
	let printerBusy = $state(false);
	let checkedAt = $state<Date | null>(null);
	let showQuality = $state(false);

	// The status card at the top of the Printer tab, from the last check.
	const isNetwork = $derived(store.main.ticket_printer_type === 'network');
	const printerStatus = $derived(
		!printerResult
			? { colour: 'neutral' as const, label: 'Not checked yet' }
			: printerResult.state === 'pending'
				? { colour: 'neutral' as const, label: 'Checking…', pending: true }
				: printerResult.state === 'ok'
					? { colour: 'green' as const, label: 'Ready' }
					: { colour: 'red' as const, label: 'Not reachable' }
	);
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
			`${store.main.ticket_feed_lines || 0} blank lines after each ticket`,
			{ partial: 'Partial cut', full: 'Full cut' }[store.main.ticket_cut as string] ?? 'No cut'
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
		printerResult = await runCheck(() =>
			raw(
				api.POST('/api/v2/settings/test-printer/', {
					body: {
						printer_type: store.main.ticket_printer_type,
						device: store.main.ticket_printer_device.trim() || null,
						host: store.main.ticket_printer_host.trim() || null,
						port: parseInt(store.main.ticket_printer_port, 10) || null
					}
				})
			)
		);
		printerBusy = false;
		checkedAt = new Date();
	}

	async function testPrint() {
		printerBusy = true;
		await attempt(async () => {
			const data = await unwrap(api.POST('/api/v2/tickets/test', { body: { include_seat: true } }));
			showToast(`Test ticket printed${data.seat ? ` (seat ${data.seat})` : ''}`, 'success');
		}, 'Failed to print test ticket');
		printerBusy = false;
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
			resetResult = { state: 'error', message: errorText(e, 'Reset failed') };
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

			<section class="space-y-4 border border-border bg-surface-1 p-4">
				<h3 class="text-sm font-medium">Connection</h3>
				<div>
					<span class="mb-1.5 block text-xs font-medium text-muted">Connected by</span>
					<div
						class="inline-flex border border-border-strong"
						role="group"
						aria-label="Connected by"
					>
						{#each [['file', 'USB cable'], ['network', 'Network']] as [type, label] (type)}
							<button
								type="button"
								class="h-[2.1rem] border-r border-border-strong px-[0.9rem] text-[0.85rem] font-medium text-muted last:border-r-0 hover:text-text aria-pressed:bg-surface-3 aria-pressed:text-text"
								aria-pressed={(type === 'network') === isNetwork}
								onclick={() => (store.main.ticket_printer_type = type)}>{label}</button
							>
						{/each}
					</div>
				</div>
				<div class="grid max-w-2xl gap-4 sm:grid-cols-2">
					{#if isNetwork}
						<div class="grid grid-cols-[minmax(0,1fr)_6rem] gap-3">
							<StoreField {store} {...HOST} />
							<StoreField {store} {...PORT} />
						</div>
					{:else}
						<StoreField {store} {...DEVICE} />
					{/if}
					<StoreField {store} {...PAPER} />
				</div>
				{#if isNetwork}
					<p class="text-xs text-muted">
						A printer on another machine can be shared with, for example,
						<code class="font-mono">socat TCP-LISTEN:9100,fork,reuseaddr OPEN:/dev/usb/lp0</code>.
					</p>
				{/if}
			</section>

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
						{#each QUALITY as f (f.id)}
							{#if isNetwork || f.field !== 'ticket_printer_timeout'}
								<StoreField {store} {...f} />
							{/if}
						{/each}
					</div>
				{/if}
			</section>

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
		<TicketDesigner {confirm} />
	{/if}
</div>
