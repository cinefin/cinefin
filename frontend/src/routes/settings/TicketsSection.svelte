<script lang="ts">
	import { Plug, Plus, Receipt, RotateCcw } from '@lucide/svelte';
	import { goto } from '$app/navigation';
	import { base } from '$app/paths';
	import { api, unwrap } from '$lib/api/client';
	import { query } from '$lib/api/query.svelte';
	import { mutate } from '$lib/api/mutate';
	import { attempt, errorText, raw, runCheck, type SettingsStore } from '$lib/settings/form.svelte';
	import { showToast } from '$lib/toast.svelte';
	import type { CheckState } from '$lib/settings/types';
	import Button from '$lib/components/ui/Button.svelte';
	import Menu, { type MenuItem } from '$lib/components/ui/Menu.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import { STARTERS } from '$lib/tickets/kinds';
	import SettingList from './SettingList.svelte';
	import SettingLists from './SettingLists.svelte';
	import SettingRow from './SettingRow.svelte';
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import StatusLamp from '$lib/components/StatusLamp.svelte';
	import CheckResult from './CheckResult.svelte';
	import StoreField, { storeField } from '$lib/settings/StoreField.svelte';

	let { store }: { store: SettingsStore } = $props();

	// The designs; each opens its own page (settings/tickets/[id]).
	const designs = query(() => raw(api.GET('/api/v2/tickets/designs')));
	const designHref = (id: number) => `${base}/settings/tickets/${id}`;
	const usage = (d: { lines: number; programmes: number; is_default: boolean }) =>
		[
			`${d.lines} line${d.lines === 1 ? '' : 's'}`,
			d.programmes
				? `picked by ${d.programmes} programme${d.programmes === 1 ? '' : 's'}`
				: d.is_default
					? 'for programmes without their own'
					: null
		]
			.filter(Boolean)
			.join(' · ');
	const starterItems: MenuItem[] = STARTERS.map((s) => ({
		label: s.label,
		onclick: () =>
			void attempt(async () => {
				const d = await raw(
					api.POST('/api/v2/tickets/designs', { body: { name: 'New design', starter: s.id } })
				);
				await goto(designHref(d.id));
			}, 'Could not create design')
	}));

	// ?view=printer (the box office's "printer settings" link) opens on the printer.
	onMount(() => {
		if (page.url.searchParams.get('view') === 'printer') {
			document.getElementById('tickets-printer')?.scrollIntoView();
		}
	});

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
			store.main.ticket_paper_width === '576' ? '80 mm roll' : '58 mm roll'
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

	// Check once when the section opens, so the printer's status card has something to say.
	onMount(() => void checkPrinter());

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

	// Reset acts on the saved config (a change still waiting to save is not included).
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

<SettingLists wider="second">
	<SettingList title="Designs" text="A programme can pick its own; the default is for the rest">
		{#snippet actions()}
			<Menu items={starterItems} label="New design" icon={Plus} size="sm" />
		{/snippet}
		{#if !designs.data}
			<div class="px-4 py-3"><Spinner size="sm" label="Loading designs…" /></div>
		{:else}
			{#each designs.data as d (d.id)}
				<SettingRow label={d.name} summary={usage(d)} onclick={() => void goto(designHref(d.id))}>
					{#snippet labelSnippet()}
						<span
							class="h-[1.125rem] w-3.5 shrink-0 border border-border bg-white"
							aria-hidden="true"
						></span>
						<span class="font-medium">{d.name}</span>
						{#if d.is_default}<span class="text-[0.7rem] text-warning">Default</span>{/if}
					{/snippet}
				</SettingRow>
			{/each}
		{/if}
	</SettingList>

	<div id="tickets-printer" class="scroll-mt-20">
		<SettingList title="Printer" text="The thermal printer tickets print on">
			<SettingRow
				label="Printer"
				hint={checkedAt
					? `Checked ${checkedAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
					: 'Not checked yet'}
			>
				{#snippet summarySnippet()}
					<StatusLamp colour={printerStatus.colour} pending={printerStatus.pending}>
						<span class="text-text">{printerStatus.label}</span>
						{#if printerResult?.state === 'error'}<span class="text-muted">
								· {printerResult.message}</span
							>{/if}
					</StatusLamp>
				{/snippet}
				{#snippet control()}
					<Button size="sm" disabled={printerBusy} onclick={checkPrinter}>
						<Plug size={13} /> Check
					</Button>
					<Button size="sm" variant="primary" disabled={printerBusy} onclick={testPrint}>
						<Receipt size={13} /> Print a test ticket
					</Button>
				{/snippet}
			</SettingRow>

			<SettingRow label="Connection" hint="USB cable or network" mono summary={printerSummary}>
				<div class="space-y-4">
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
				</div>
			</SettingRow>

			<SettingRow label="Print quality" summary={qualitySummary}>
				<div class="grid max-w-2xl gap-4 sm:grid-cols-2">
					{#each QUALITY as f (f.id)}
						{#if isNetwork || f.field !== 'ticket_printer_timeout'}
							<StoreField {store} {...f} />
						{/if}
					{/each}
				</div>
			</SettingRow>

			<SettingRow
				label="Printing garbage?"
				hint="After a garbled print"
				summary="Clears a stuck printer without a power cycle"
			>
				{#snippet control()}
					<Button size="sm" disabled={printerBusy} onclick={resetPrinter}>
						<RotateCcw size={13} /> Reset printer
					</Button>
				{/snippet}
			</SettingRow>
		</SettingList>
		<CheckResult result={resetResult} />
	</div>
</SettingLists>
