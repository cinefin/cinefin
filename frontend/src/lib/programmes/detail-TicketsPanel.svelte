<script lang="ts">
	import { base } from '$app/paths';
	import { ChevronDown, Minus, Plus, Printer, Receipt, RotateCcw } from '@lucide/svelte';
	import { api, toApiError, unwrap } from '$lib/api/client';
	import type { components } from '$lib/api/types.gen';
	import Button from '$lib/components/ui/Button.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import { showToast } from '$lib/toast.svelte';

	type Schedule = components['schemas']['ScheduleSchema'];
	type SeatMap = components['schemas']['SeatMapDataSchema'];
	type IssuedTicket = components['schemas']['TicketIssueSchema'];
	type DesignSummary = components['schemas']['DesignSummarySchema'];
	type PrintData = components['schemas']['TicketPrintDataSchema'];

	interface Props {
		programmeId: number;
		programmeName: string;
		designs: DesignSummary[];
		designId: number | null;
		onchange: (designId: number | null) => void;
	}

	let { programmeId, programmeName, designs, designId, onchange }: Props = $props();

	const designValue = $derived(designId === null ? '' : String(designId));
	const defaultDesign = $derived(designs.find((d) => d.is_default));

	let savingDesign = $state(false);
	let sessionCount = $state(0);
	let issuedCount = $state(0);
	let qty = $state(1);
	let printing = $state(false);
	let testing = $state(false);
	let resetting = $state(false);

	let schedules = $state<Schedule[]>([]);
	let scheduleId = $state(''); // '' = now (no schedule)

	let seatsOpen = $state(false);
	let seatMap = $state<SeatMap | null>(null);
	let seatMapLoading = $state(false);
	let seatMapError = $state(false);
	let selectedSeats = $state<string[]>([]);

	let history = $state<IssuedTicket[]>([]);
	let historyFailed = $state(false);
	let reprinting = $state<number | null>(null);

	// Fresh session per programme.
	$effect(() => {
		void programmeId;
		sessionCount = 0;
		qty = 1;
		selectedSeats = [];
		seatsOpen = false;
		seatMap = null;
		seatMapError = false;
		void loadSchedules();
		void refreshHistory();
	});

	async function selectDesign(next: string) {
		if (savingDesign) return;
		savingDesign = true;
		const id = next ? parseInt(next, 10) : null;
		try {
			const res = await api.POST('/api/v2/tickets/programmes/{programme_id}/design', {
				params: { path: { programme_id: programmeId } },
				body: { design_id: id }
			});
			if (res.error) throw new Error('Could not set the ticket design');
			showToast('Ticket design updated', 'success');
			onchange(id);
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Could not set the ticket design', 'error');
		} finally {
			savingDesign = false;
		}
	}

	async function loadSchedules() {
		try {
			const data = await unwrap(
				api.GET('/api/v2/schedules/list', {
					params: { query: { programme_id: programmeId, status: 'scheduled' } }
				})
			);
			const now = Date.now();
			schedules = (data?.schedules ?? [])
				.filter((s) => s.status === 'scheduled' && new Date(s.start_time).getTime() > now)
				.sort((a, b) => new Date(a.start_time).getTime() - new Date(b.start_time).getTime());
			scheduleId = schedules.length ? String(schedules[0].id) : '';
		} catch (e) {
			console.error('Failed to load schedules for tickets:', e);
			schedules = [];
			scheduleId = '';
		}
	}

	function onShowtimeChange() {
		selectedSeats = [];
		if (seatMap) void refreshSeatMap();
	}

	function formatShowtime(iso: string): string {
		const d = new Date(iso);
		return (
			d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' }) +
			', ' +
			d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
		);
	}

	function toggleSeatPanel() {
		seatsOpen = !seatsOpen;
		if (seatsOpen && !seatMap && !seatMapLoading) void refreshSeatMap();
	}

	async function refreshSeatMap() {
		seatMapLoading = true;
		seatMapError = false;
		try {
			const data = await unwrap(
				api.GET('/api/v2/tickets/seats', {
					params: {
						query: {
							programme_id: programmeId,
							schedule_id: scheduleId ? parseInt(scheduleId, 10) : null
						}
					}
				})
			);
			seatMap = data ?? null;
			// Drop any selections that have since been taken.
			const occ = new Set(data?.occupied ?? []);
			selectedSeats = selectedSeats.filter((s) => !occ.has(s));
		} catch (e) {
			console.error('Failed to load seat map:', e);
			seatMapError = true;
		} finally {
			seatMapLoading = false;
		}
	}

	function toggleSeat(seat: string) {
		selectedSeats = selectedSeats.includes(seat)
			? selectedSeats.filter((s) => s !== seat)
			: [...selectedSeats, seat];
	}

	// Picked seats drive the print (one ticket each) and lock the quantity.
	const seatsLocked = $derived(selectedSeats.length > 0);
	const effectiveQty = $derived(seatsLocked ? selectedSeats.length : qty);
	const seatLabel = $derived(selectedSeats.length ? selectedSeats.join(', ') : 'auto');

	function stepQty(delta: number) {
		qty = Math.min(20, Math.max(1, (qty || 1) + delta));
	}

	function afterPrint(data: PrintData | undefined) {
		const seats = (data?.seats ?? []).filter(Boolean);
		const nums = (data?.ticket_numbers ?? []).map((n) => `#${n}`).join(', ');
		const printed = data?.copies || seats.length || 1;
		const seatText = seats.length
			? ` - seat${seats.length > 1 ? 's' : ''} ${seats.join(', ')}`
			: '';
		showToast(`${programmeName}: ${nums || 'printed'}${seatText}`, 'success');

		sessionCount += printed;
		selectedSeats = [];
		if (seatMap) void refreshSeatMap();
		void refreshHistory();
	}

	async function printTickets() {
		if (printing) return;
		printing = true;
		try {
			const body: components['schemas']['ProgrammeTicketRequestSchema'] = {
				copies: Math.min(20, Math.max(1, effectiveQty || 1)),
				seats: selectedSeats.length ? [...selectedSeats] : null,
				schedule_id: scheduleId ? parseInt(scheduleId, 10) : null
			};
			const data = await unwrap(
				api.POST('/api/v2/tickets/print/programme/{programme_id}', {
					params: { path: { programme_id: programmeId } },
					body
				})
			);
			afterPrint(data);
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Failed to print programme ticket', 'error');
		} finally {
			printing = false;
		}
	}

	async function testPrint() {
		if (testing) return;
		testing = true;
		try {
			await unwrap(api.POST('/api/v2/tickets/test', { body: { include_seat: true } }));
			showToast('Test ticket printed', 'success');
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Failed to print test ticket', 'error');
		} finally {
			testing = false;
		}
	}

	async function resetPrinter() {
		if (resetting) return;
		resetting = true;
		try {
			const res = await api.POST('/api/v2/tickets/reset');
			if (res.error) throw toApiError(res.error, res.response);
			showToast(res.data?.message || 'Printer reset', 'success');
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Failed to reset printer', 'error');
		} finally {
			resetting = false;
		}
	}

	async function refreshHistory() {
		try {
			const data = await unwrap(
				api.GET('/api/v2/tickets/issued', { params: { query: { programme_id: programmeId } } })
			);
			history = data?.tickets ?? [];
			issuedCount = data?.count ?? history.length;
			historyFailed = false;
		} catch (e) {
			console.error('Failed to load ticket history:', e);
			historyFailed = true;
		}
	}

	async function reprint(issue: IssuedTicket) {
		if (reprinting !== null) return;
		reprinting = issue.id;
		try {
			const res = await api.POST('/api/v2/tickets/reprint/{issue_id}', {
				params: { path: { issue_id: issue.id } }
			});
			if (res.error) throw toApiError(res.error, res.response);
			showToast(res.data?.message || 'Reprinted', 'success');
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'Failed to reprint ticket', 'error');
		} finally {
			reprinting = null;
		}
	}

	function formatPrintedAt(iso: string): string {
		const d = new Date(iso);
		const time = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
		if (d.toDateString() === new Date().toDateString()) return time;
		return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) + ' ' + time;
	}

	// Enter fires the primary print for rapid repeats, but not from a seat/button/link.
	function onKeydown(e: KeyboardEvent) {
		if (e.key !== 'Enter') return;
		const t = e.target as HTMLElement;
		if (t.closest('[data-seat-grid]') || t.tagName === 'BUTTON' || t.tagName === 'A') return;
		e.preventDefault();
		void printTickets();
	}
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="max-w-2xl space-y-4 p-4" onkeydown={onKeydown}>
	<div class="flex flex-wrap items-end gap-3">
		{#if schedules.length}
			<label class="flex flex-col gap-1 text-xs text-muted">
				Showtime
				<Select bind:value={scheduleId} onchange={onShowtimeChange}>
					{#each schedules as s (s.id)}
						<option value={String(s.id)}>{formatShowtime(s.start_time)}</option>
					{/each}
					<option value="">Now (no schedule)</option>
				</Select>
			</label>
		{/if}
		<label class="flex flex-col gap-1 text-xs text-muted">
			Design
			<Select
				value={designValue}
				disabled={savingDesign}
				onchange={(e) => void selectDesign((e.currentTarget as HTMLSelectElement).value)}
			>
				<option value="">Default{defaultDesign ? ` - ${defaultDesign.name}` : ''}</option>
				{#each designs as d (d.id)}
					<option value={String(d.id)}>{d.name}</option>
				{/each}
			</Select>
		</label>
		<div class="ml-auto pb-2 font-mono text-xs text-muted">
			<span title="Printed since you opened this page">
				<strong class="text-text">{sessionCount}</strong> this session
			</span>
			<span class="mx-1">·</span>
			<span title="All tickets issued for this programme">{issuedCount} issued</span>
		</div>
	</div>

	<div class="flex flex-wrap items-start gap-4">
		<div class="flex items-center gap-2">
			<span class="text-xs text-muted">Qty</span>
			<div class="flex items-center rounded-md border border-border-strong">
				<button
					type="button"
					class="flex h-9 w-8 items-center justify-center text-muted hover:bg-surface-2 hover:text-text disabled:opacity-45"
					aria-label="Fewer"
					disabled={seatsLocked}
					onclick={() => stepQty(-1)}
				>
					<Minus size={13} />
				</button>
				<span class="w-8 text-center font-mono text-sm">{effectiveQty}</span>
				<button
					type="button"
					class="flex h-9 w-8 items-center justify-center text-muted hover:bg-surface-2 hover:text-text disabled:opacity-45"
					aria-label="More"
					disabled={seatsLocked}
					onclick={() => stepQty(1)}
				>
					<Plus size={13} />
				</button>
			</div>
		</div>

		<div class="min-w-0 flex-1">
			<button
				type="button"
				class="flex items-center gap-2 text-sm text-muted hover:text-text"
				onclick={toggleSeatPanel}
			>
				<span class="text-xs">Seat</span>
				<span class="font-mono text-text">{seatLabel}</span>
				<ChevronDown size={13} class={seatsOpen ? 'rotate-180' : ''} />
			</button>
			{#if seatsOpen}
				<p class="mt-2 text-xs text-muted">
					Pick one or more seats - each prints its own ticket. Leave unpicked to auto-assign.
				</p>
				{#if seatMapLoading}
					<Spinner size="sm" />
				{:else if seatMapError}
					<p class="mt-2 text-xs text-danger">Failed to load seat map</p>
				{:else if seatMap}
					<div class="mt-2 overflow-x-auto">
						<div
							data-seat-grid
							class="grid w-max gap-1"
							style="grid-template-columns: auto repeat({seatMap.seats_per_row}, 1.5rem)"
						>
							<div></div>
							{#each Array(seatMap.seats_per_row) as _, c (c)}
								<div class="text-center font-mono text-[0.65rem] text-faint">{c + 1}</div>
							{/each}
							{#each Array(seatMap.rows) as _, r (r)}
								{@const letter = String.fromCharCode(65 + r)}
								<div class="pr-1 text-right font-mono text-[0.65rem] leading-6 text-faint">
									{letter}
								</div>
								{#each Array(seatMap.seats_per_row) as _, c (c)}
									{@const seat = `${letter}${c + 1}`}
									{@const occupied = seatMap.occupied.includes(seat)}
									{@const selected = selectedSeats.includes(seat)}
									<button
										type="button"
										class="h-6 w-6 rounded-sm border text-[0.6rem]
											{occupied
											? 'cursor-not-allowed border-border bg-surface-3 opacity-40'
											: selected
												? 'border-accent bg-accent/30'
												: 'border-border-strong bg-surface-2 hover:bg-surface-3'}"
										title="{seat}{occupied ? ' - taken' : ''}"
										aria-label="Seat {seat}{occupied ? ' - taken' : ''}"
										disabled={occupied}
										onclick={() => toggleSeat(seat)}
									></button>
								{/each}
							{/each}
						</div>
					</div>
				{/if}
			{/if}
		</div>
	</div>

	<div>
		<Button
			variant="primary"
			class="w-full"
			disabled={printing}
			onclick={() => void printTickets()}
		>
			<Printer size={14} />
			{printing ? 'Printing…' : 'Print tickets'}
		</Button>
		<p class="mt-1.5 text-xs text-muted">
			A ticket admits to the whole programme - its features are listed on the ticket.
		</p>
	</div>

	<details class="rounded-md border border-border">
		<summary class="cursor-pointer px-3 py-2 text-sm text-muted select-none hover:text-text">
			Recent prints
		</summary>
		<ul class="max-h-48 divide-y divide-border overflow-y-auto border-t border-border">
			{#if historyFailed}
				<li class="px-3 py-2 text-xs text-danger">Failed to load ticket history</li>
			{:else if !history.length}
				<li class="px-3 py-2 text-xs text-faint">None yet</li>
			{:else}
				{#each history.slice(0, 10) as t (t.id)}
					<li class="flex items-center gap-3 px-3 py-1.5 font-mono text-xs">
						<span class="text-accent">#{t.ticket_number}</span>
						<span class="w-8">{t.seat || '-'}</span>
						<span class="min-w-0 flex-1 truncate text-muted" title={t.title}>
							{t.title || t.kind}
						</span>
						<span class="text-faint">{formatPrintedAt(t.printed_at)}</span>
						<button
							type="button"
							class="rounded-sm p-1 text-muted hover:bg-surface-2 hover:text-text disabled:opacity-45"
							title="Reprint this ticket"
							disabled={reprinting !== null}
							onclick={() => void reprint(t)}
						>
							<Printer size={12} />
						</button>
					</li>
				{/each}
				{#if history.length > 10}
					<li class="px-3 py-1.5 text-xs text-faint">…and {history.length - 10} more</li>
				{/if}
			{/if}
		</ul>
	</details>

	<div class="flex flex-wrap items-center gap-2 border-t border-border pt-3">
		<Button
			size="sm"
			disabled={testing}
			title="Print a sample ticket to check the printer"
			onclick={() => void testPrint()}
		>
			<Receipt size={13} /> Test print
		</Button>
		<Button
			size="sm"
			disabled={resetting}
			title="Clear a printer that's spitting garbage - no power-cycle needed"
			onclick={() => void resetPrinter()}
		>
			<RotateCcw size={13} /> Reset printer
		</Button>
		<p class="ml-auto text-xs text-faint">
			Printer, paper and seating are global -
			<a class="text-accent hover:underline" href="{base}/settings?tab=tickets">
				Settings → Tickets
			</a>
		</p>
	</div>
</div>
