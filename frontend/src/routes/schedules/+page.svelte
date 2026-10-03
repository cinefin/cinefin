<script lang="ts">
	import PageHeader from '$lib/components/shell/PageHeader.svelte';
	import LeadInSteps, { type LeadInStep } from '$lib/schedules/LeadInSteps.svelte';
	import { base } from '$app/paths';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import {
		Calendar,
		CalendarPlus,
		ChevronLeft,
		ChevronRight,
		Clock,
		Eye,
		List,
		Pencil,
		Plus,
		Trash2,
		TriangleAlert
	} from '@lucide/svelte';
	import { api, unwrap, toApiError } from '$lib/api/client';
	import { mutate } from '$lib/api/mutate';
	import { query } from '$lib/api/query.svelte';
	import { invalidate } from '$lib/invalidate';
	import { NoticeState } from '$lib/notice.svelte';
	import type { components } from '$lib/api/types.gen';
	import { formatClock } from '$lib/format';
	import ActionNotice from '$lib/components/ActionNotice.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import FeatureStack from '$lib/components/FeatureStack.svelte';
	import Dialog from '$lib/components/ui/Dialog.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Toggle from '$lib/components/ui/Toggle.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';

	type Schedule = components['schemas']['ScheduleSchema'];
	type ProgrammeListItem = components['schemas']['ProgrammeListItemSchema'];

	const notice = new NoticeState();

	// One fetch with show_past=true; the status chips and "Show past" toggle filter client-side.
	const schedules = query(() =>
		unwrap(api.GET('/api/v2/schedules/list', { params: { query: { show_past: true } } }))
	);
	$effect(() => schedules.live({ everyMs: 20_000, keys: ['schedules', 'programmes'] }));

	const programmes = query(() => unwrap(api.GET('/api/v2/programmes/list')));

	const byStart = (a: Schedule, b: Schedule) =>
		new Date(a.start_time).getTime() - new Date(b.start_time).getTime();
	const all = $derived(((schedules.data?.schedules ?? []) as Schedule[]).toSorted(byStart));
	const progList = $derived((programmes.data?.programmes ?? []) as ProgrammeListItem[]);
	const features = $derived(Object.fromEntries(progList.map((p) => [p.id, p.movies])));
	const runtimes: Record<number, number> = $derived(
		Object.fromEntries(progList.map((p) => [p.id, Math.round(p.total_runtime)]))
	);

	type Variant = 'default' | 'accent' | 'success' | 'warning' | 'danger';
	// status: [label, badge variant, calendar chip classes]
	const STATUS: Record<string, [string, Variant, string]> = {
		scheduled: ['Scheduled', 'default', 'bg-surface-3 text-text'],
		running: ['Running', 'accent', 'bg-accent/20 text-accent'],
		completed: ['Completed', 'success', 'bg-success/15 text-success'],
		cancelled: ['Cancelled', 'warning', 'bg-warning/15 text-warning'],
		failed: ['Failed', 'danger', 'bg-danger/15 text-danger'],
		missed: ['Missed', 'warning', 'bg-warning/15 text-warning']
	};
	const STATUSES = [
		{ value: '', label: 'All' },
		...Object.entries(STATUS).map(([value, [label]]) => ({ value, label }))
	];

	let statusFilter = $state('');
	let showPast = $state(false);
	let view = $state<'list' | 'calendar'>(
		localStorage.getItem('sched.view') === 'calendar' ? 'calendar' : 'list'
	);
	const VIEWS = [
		{ v: 'list', label: 'List view', Icon: List },
		{ v: 'calendar', label: 'Calendar view', Icon: Calendar }
	] as const;

	const statusCounts = $derived.by(() => {
		const c: Record<string, number> = {};
		for (const s of all) c[s.status] = (c[s.status] ?? 0) + 1;
		return c;
	});
	const activeCount = $derived((statusCounts.scheduled ?? 0) + (statusCounts.running ?? 0));
	const todayCount = $derived.by(() => {
		const today = new Date().toDateString();
		return all.filter((s) => new Date(s.start_time).toDateString() === today).length;
	});

	function endMs(s: Schedule): number {
		if (s.end_time) return new Date(s.end_time).getTime();
		return new Date(s.play_time).getTime() + (s.runtime || 0) * 60000;
	}

	const filtered = $derived(all.filter((s) => !statusFilter || s.status === statusFilter));
	const visible = $derived.by(() => {
		const now = Date.now();
		return filtered.filter((s) => showPast || endMs(s) >= now);
	});

	function groupByDay(list: Schedule[]): Map<string, Schedule[]> {
		const byDay = new Map<string, Schedule[]>();
		for (const s of list) {
			const key = new Date(s.start_time).toDateString();
			byDay.set(key, [...(byDay.get(key) ?? []), s]);
		}
		return byDay;
	}
	const dayGroups = $derived(groupByDay(visible));

	const filtersActive = $derived(Boolean(statusFilter) || showPast);

	const MAX_CHIPS = 3;
	function firstOfMonth(d: Date): Date {
		return new Date(d.getFullYear(), d.getMonth(), 1);
	}
	let calMonth = $state(firstOfMonth(new Date()));
	function shiftMonth(delta: number) {
		calMonth = new Date(calMonth.getFullYear(), calMonth.getMonth() + delta, 1);
	}

	// 6-week Monday-first grid; the status filter applies, "Show past" does not.
	const calCells = $derived.by(() => {
		const byDay = groupByDay(filtered);
		const firstWeekday = (calMonth.getDay() + 6) % 7; // Monday = 0
		const todayKey = new Date().toDateString();
		return Array.from({ length: 42 }, (_, i) => {
			const day = new Date(calMonth.getFullYear(), calMonth.getMonth(), 1 - firstWeekday + i);
			const key = day.toDateString();
			return {
				day,
				outside: day.getMonth() !== calMonth.getMonth(),
				today: key === todayKey,
				items: byDay.get(key) ?? []
			};
		});
	});

	function dayLabel(d: Date): string {
		const today = new Date();
		today.setHours(0, 0, 0, 0);
		const that = new Date(d);
		that.setHours(0, 0, 0, 0);
		const diff = Math.round((that.getTime() - today.getTime()) / 86400000);
		const date = d.toLocaleDateString(undefined, {
			weekday: 'short',
			day: 'numeric',
			month: 'short'
		});
		if (diff === 0) return `Today · ${date}`;
		if (diff === 1) return `Tomorrow · ${date}`;
		if (diff === -1) return `Yesterday · ${date}`;
		return date;
	}

	function relTime(s: Schedule): string {
		if (s.status === 'running') return 'On now';
		if (s.status === 'completed') return 'Finished';
		if (s.status === 'cancelled') return '';
		const ms = new Date(s.start_time).getTime() - Date.now();
		if (ms < 0) return '';
		const mins = Math.round(ms / 60000);
		if (mins < 60) return `in ${mins} min`;
		const hrs = Math.round(mins / 60);
		if (hrs < 24) return `in ${hrs} h`;
		return `in ${Math.round(hrs / 24)} d`;
	}

	function cancelTitle(s: Schedule): string {
		if (s.status === 'running') return 'Remove schedule (does not stop playback)';
		return s.status === 'scheduled' ? 'Cancel schedule' : 'Remove from list';
	}

	// "YYYY-MM-DDTHH:MM" (datetime-local) -> ms treating the value as wall-clock
	// (UTC-based, so plain arithmetic has no DST surprises). null if unparsable.
	function parseWallClock(dt: string): number | null {
		const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(dt || '');
		if (!m) return null;
		return Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
	}

	function tzOffsetMs(epochMs: number, tz: string): number | null {
		try {
			const dtf = new Intl.DateTimeFormat('en-US', {
				timeZone: tz,
				hourCycle: 'h23',
				year: 'numeric',
				month: '2-digit',
				day: '2-digit',
				hour: '2-digit',
				minute: '2-digit'
			});
			const p = Object.fromEntries(dtf.formatToParts(epochMs).map((x) => [x.type, x.value]));
			const asUTC = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute);
			return asUTC - Math.floor(epochMs / 60000) * 60000;
		} catch {
			return null;
		}
	}

	// datetime-local value as wall-clock in `tz` -> epoch ms. Two-pass so DST converges.
	function wallClockToEpoch(dt: string, tz: string): number | null {
		const wall = parseWallClock(dt);
		if (wall == null) return null;
		if (!tz) return new Date(dt).getTime();
		const offset = tzOffsetMs(wall, tz);
		if (offset == null) return new Date(dt).getTime();
		let epoch = wall - offset;
		const second = tzOffsetMs(epoch, tz);
		if (second != null && second !== offset) epoch = wall - second;
		return epoch;
	}

	function fmtTimeIn(d: Date, tz: string): string {
		try {
			return d.toLocaleTimeString('en-GB', {
				hour: '2-digit',
				minute: '2-digit',
				timeZone: tz || undefined
			});
		} catch {
			return formatClock(d);
		}
	}

	// Date -> local "YYYY-MM-DDTHH:MM" for a datetime-local input.
	function toLocalInput(d: Date): string {
		d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
		return d.toISOString().slice(0, 16);
	}

	function defaultDateTime(): string {
		const d = new Date();
		d.setMinutes(d.getMinutes() + 5 - (d.getMinutes() % 5), 0, 0); // round up to next 5 min
		return toLocalInput(d);
	}

	function timezoneList(): string[] {
		let zones: string[];
		try {
			zones = Intl.supportedValuesOf('timeZone');
		} catch {
			zones = [
				'UTC',
				'Europe/London',
				'Europe/Paris',
				'Europe/Berlin',
				'America/New_York',
				'America/Los_Angeles',
				'Asia/Tokyo',
				'Australia/Sydney'
			];
		}
		const current = Intl.DateTimeFormat().resolvedOptions().timeZone;
		if (current && !zones.includes(current)) zones = [current, ...zones];
		return zones;
	}
	const timezones = timezoneList();
	const browserZone = Intl.DateTimeFormat().resolvedOptions().timeZone;

	let modalOpen = $state(false);
	let editing = $state<Schedule | null>(null); // null = creating
	let selectedProgramme = $state<{ id: number; name: string } | null>(null);
	let pickerSearch = $state('');
	let dtValue = $state('');
	let dtMin = $state('');
	let tzValue = $state(browserZone);
	let leadInValue = $state(0); // minutes
	let leadInSteps = $state<LeadInStep[]>([]);
	let leadInOn = $state(false); // off = no lead-in: the programme cues and plays at the start time
	let saving = $state(false);
	let modalError = $state<string | null>(null);

	// s = the screening to reschedule, or null to create one (optionally preselecting a programme).
	function openDialog(s: Schedule | null, preselect: { id: number; name: string } | null = null) {
		editing = s;
		selectedProgramme = s ? { id: s.programme.id, name: s.programme.name } : preselect;
		pickerSearch = '';
		dtValue = s ? toLocalInput(new Date(s.start_time)) : defaultDateTime();
		dtMin = toLocalInput(new Date());
		leadInValue = s ? Math.round(s.lead_in / 60) : 0;
		leadInSteps = (s?.preshow ?? []).map((step) => ({ ...step }));
		leadInOn = !!s && (s.lead_in > 0 || leadInSteps.some((step) => !step.cue));
		modalError = null;
		tzValue = browserZone;
		modalOpen = true;
	}

	const pickerMatches = $derived.by(() => {
		const q = pickerSearch.trim().toLowerCase();
		return q ? progList.filter((p) => p.name.toLowerCase().includes(q)) : progList;
	});

	const leadInSeconds = $derived(
		leadInOn ? Math.max(0, Math.round(Number(leadInValue) || 0)) * 60 : 0
	);
	const leadInMs = $derived(leadInSeconds * 1000);

	const currentRuntime = $derived(
		editing
			? editing.runtime || runtimes[editing.programme.id] || 0
			: selectedProgramme
				? runtimes[selectedProgramme.id] || 0
				: 0
	);

	// "Lead-in 10 min · plays 20:00 · ends ~22:15". Wall-clock arithmetic in the terms the
	// start time is entered in; the lead-in counts towards the screening's length.
	const endHint = $derived.by(() => {
		const startWall = parseWallClock(dtValue);
		const runtime = currentRuntime;
		if (startWall == null) return '';
		const pad = (n: number) => String(n).padStart(2, '0');
		const clock = (d: Date) => `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
		const play = new Date(startWall + leadInMs);
		const parts = leadInMs ? [`Lead-in ${leadInMs / 60000} min`, `plays ${clock(play)}`] : [];
		if (runtime && Number.isFinite(runtime)) {
			const end = new Date(play.getTime() + Math.round(runtime) * 60000);
			const sameDay =
				dtValue.slice(0, 10) ===
				`${end.getUTCFullYear()}-${pad(end.getUTCMonth() + 1)}-${pad(end.getUTCDate())}`;
			parts.push(`ends ~${clock(end)}${sameDay ? '' : ' (next day)'}`);
		}
		const text = parts.join(' · ');
		return text && text[0].toUpperCase() + text.slice(1);
	});

	// A screening may not overlap another scheduled/running one (lead-in included); Save is
	// disabled while it does, and the server refuses it too.
	const conflict = $derived.by(() => {
		if (!dtValue || !selectedProgramme) return null;
		const runtime = currentRuntime;
		if (!runtime) return null; // unknown runtime: don't guess
		const start = wallClockToEpoch(dtValue, tzValue);
		if (start == null) return null;
		const end = start + leadInMs + Math.round(runtime) * 60000;

		const clash = all.find((s) => {
			if (s.id === editing?.id) return false;
			if (s.status !== 'scheduled' && s.status !== 'running') return false;
			const sStart = new Date(s.start_time).getTime();
			const sEnd = endMs(s);
			if (!Number.isFinite(sStart) || !Number.isFinite(sEnd) || sEnd <= sStart) return false;
			return sStart < end && sEnd > start;
		});
		if (!clash) return null;
		return {
			name: clash.programme.name,
			from: fmtTimeIn(new Date(clash.start_time), tzValue),
			to: fmtTimeIn(new Date(endMs(clash)), tzValue)
		};
	});

	const canSave = $derived(Boolean(dtValue) && Boolean(selectedProgramme) && !conflict);

	async function save() {
		if (!canSave || saving) return;
		saving = true;
		modalError = null;
		try {
			const body = {
				start_time: dtValue,
				timezone: tzValue,
				lead_in: leadInSeconds,
				preshow: leadInOn ? leadInSteps : []
			};
			if (editing) {
				const path = { schedule_id: editing.id };
				await unwrap(api.PUT('/api/v2/schedules/{schedule_id}', { params: { path }, body }));
			} else {
				const programme_id = selectedProgramme!.id;
				await unwrap(api.POST('/api/v2/schedules/create', { body: { programme_id, ...body } }));
			}
			notice.show('success', editing ? 'Schedule updated' : 'Schedule created');
			modalOpen = false;
			invalidate('schedules');
		} catch (e) {
			modalError = toApiError(e).message || 'Failed to save schedule';
		} finally {
			saving = false;
		}
	}

	let confirmOpen = $state(false);
	let confirmTarget = $state<Schedule | null>(null);
	let removing = $state(false);

	async function confirmRemove() {
		const target = confirmTarget;
		if (!target || removing) return;
		removing = true;
		try {
			await mutate(
				api.DELETE('/api/v2/schedules/{schedule_id}', {
					params: { path: { schedule_id: target.id } }
				})
			);
			notice.show('success', 'Schedule removed');
			invalidate('schedules');
		} catch (e) {
			notice.show('error', toApiError(e).message || 'Failed to remove schedule');
		} finally {
			confirmOpen = false;
			removing = false;
		}
	}

	// Deep link: /schedules?new=<programmeId> opens the create modal pre-selected.
	let deepLinkId = $state<number | null>(Number(page.url.searchParams.get('new') ?? '') || null);
	$effect(() => {
		if (deepLinkId == null || !programmes.data) return;
		const wanted = progList.find((p) => p.id === deepLinkId);
		deepLinkId = null;
		void goto(`${base}/schedules`, { replaceState: true }); // don't reopen on refresh
		openDialog(null, wanted ?? null);
	});
</script>

<PageHeader title="Schedules" count="{activeCount} active · {todayCount} today" {actions} />
{#snippet actions()}
	<Button variant="primary" onclick={() => openDialog(null)}>
		<Plus size={14} /> New schedule
	</Button>
{/snippet}

<ActionNotice {notice} class="mb-4" />

<div class="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2">
	<div class="flex flex-wrap gap-1.5" role="group" aria-label="Filter schedules by status">
		{#each STATUSES as st (st.value)}
			{@const active = statusFilter === st.value}
			<button
				type="button"
				aria-pressed={active}
				onclick={() => (statusFilter = st.value)}
				class="inline-flex h-7 items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium
					transition-colors
					{active
					? 'border-accent-dim bg-accent/15 text-accent'
					: 'border-border-strong bg-surface-2 text-muted hover:bg-surface-3 hover:text-text'}"
			>
				{st.label}
				<span class="font-mono text-[0.65rem] opacity-70">
					{st.value === '' ? all.length : (statusCounts[st.value] ?? 0)}
				</span>
			</button>
		{/each}
	</div>

	<div class="ml-auto flex items-center gap-3">
		{#if view === 'list'}
			<label class="flex cursor-pointer items-center gap-1.5 text-sm text-muted select-none">
				<input type="checkbox" bind:checked={showPast} class="accent-accent" />
				Show past
			</label>
		{/if}
		<div
			class="flex overflow-hidden rounded-md border border-border-strong"
			role="group"
			aria-label="Switch view"
		>
			{#each VIEWS as o, i (o.v)}
				<button
					type="button"
					title={o.label}
					aria-label={o.label}
					aria-pressed={view === o.v}
					onclick={() => {
						view = o.v;
						localStorage.setItem('sched.view', o.v);
					}}
					class="flex h-7 w-8 items-center justify-center {i ? 'border-l border-border-strong' : ''}
						{view === o.v ? 'bg-surface-3 text-accent' : 'bg-surface-2 text-muted hover:text-text'}"
				>
					<o.Icon size={14} />
				</button>
			{/each}
		</div>
	</div>
</div>

{#if schedules.loading}
	<Spinner label="Loading schedules…" />
{:else if schedules.error}
	<ErrorState error={schedules.error} retry={() => void schedules.load()} />
{:else if view === 'calendar'}
	<div class="rounded-lg border border-border bg-surface-1">
		<div class="flex items-center justify-between gap-3 border-b border-border px-3 py-2">
			<div class="flex items-center gap-1">
				<Button size="sm" variant="ghost" title="Previous month" onclick={() => shiftMonth(-1)}>
					<ChevronLeft size={14} />
				</Button>
				<Button
					size="sm"
					variant="ghost"
					title="Jump to this month"
					onclick={() => (calMonth = firstOfMonth(new Date()))}
				>
					Today
				</Button>
				<Button size="sm" variant="ghost" title="Next month" onclick={() => shiftMonth(1)}>
					<ChevronRight size={14} />
				</Button>
			</div>
			<div class="text-sm font-medium">
				{calMonth.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })}
			</div>
		</div>
		<div class="grid grid-cols-7 border-b border-border text-center text-[0.65rem] text-faint">
			{#each ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as wd (wd)}
				<span class="py-1.5">{wd}</span>
			{/each}
		</div>
		<div class="grid grid-cols-7">
			{#each calCells as cell, i (i)}
				<div
					class="min-h-20 border-r border-b border-border p-1 last:border-r-0
						{cell.outside ? 'bg-bg/40' : ''} {cell.today ? 'bg-accent/5' : ''}"
				>
					<div
						class="mb-1 text-right font-mono text-[0.65rem] {cell.today
							? 'font-bold text-accent'
							: cell.outside
								? 'text-faint'
								: 'text-muted'}"
					>
						{cell.day.getDate()}
					</div>
					<div class="space-y-0.5">
						{#each cell.items.slice(0, MAX_CHIPS) as s (s.id)}
							{@const t = formatClock(new Date(s.start_time))}
							<a
								href="{base}/programmes/{s.programme.id}"
								target="_blank"
								rel="noopener"
								title="{t} · {s.programme.name} ({s.status})"
								class="flex items-baseline gap-1 truncate rounded-xs px-1 py-0.5 text-[0.65rem] leading-tight {STATUS[
									s.status
								]?.[2] ?? 'bg-surface-3 text-text'}"
							>
								<span class="shrink-0 font-mono">{t}</span>
								<span class="truncate">{s.programme.name}</span>
							</a>
						{/each}
						{#if cell.items.length > MAX_CHIPS}
							<div class="px-1 text-[0.6rem] text-faint">+{cell.items.length - MAX_CHIPS} more</div>
						{/if}
					</div>
				</div>
			{/each}
		</div>
	</div>
{:else if visible.length === 0}
	{#if filtersActive}
		<EmptyState
			icon={CalendarPlus}
			title="No screenings match your filters"
			message="Try a different status filter, or toggle Show past."
		/>
	{:else}
		<EmptyState
			icon={CalendarPlus}
			title="Nothing scheduled"
			message="Use New schedule to line up a screening."
			action={actions}
		/>
	{/if}
{:else}
	<div class="space-y-6">
		{#each [...dayGroups] as [key, items] (key)}
			<section>
				<div class="mb-2 flex items-baseline gap-2">
					<h2 class="text-[0.8rem] font-medium text-muted">
						{dayLabel(new Date(key))}
					</h2>
					<span class="font-mono text-xs text-faint">{items.length}</span>
				</div>
				<div class="space-y-2">
					{#each items as s (s.id)}
						{@const start = new Date(s.start_time)}
						{@const end = new Date(endMs(s))}
						{@const rel = relTime(s)}
						<article
							class="flex items-center gap-4 rounded-lg border border-border bg-surface-1 p-3"
						>
							<div class="w-16 shrink-0 text-right">
								<div class="font-mono text-sm font-semibold">{formatClock(start)}</div>
								<div class="font-mono text-xs text-faint">→ {formatClock(end)}</div>
							</div>
							<FeatureStack films={features[s.programme.id] ?? []} class="w-[4.75rem] shrink-0" />
							<div class="min-w-0 flex-1">
								<a
									href="{base}/programmes/{s.programme.id}"
									title="Open programme"
									class="block truncate text-sm font-medium hover:text-accent"
								>
									{s.programme.name}
								</a>
								<div class="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
									<Badge variant={STATUS[s.status]?.[1] ?? 'default'}>{s.status}</Badge>
									<span class="inline-flex items-center gap-1">
										<Clock size={12} />
										{s.runtime} min
									</span>
									{#if s.play_time !== s.start_time}
										<span class="font-mono text-faint"
											>plays {formatClock(new Date(s.play_time))}</span
										>
									{/if}
									{#if rel}<span class="text-faint">{rel}</span>{/if}
								</div>
								{#if s.status === 'failed' && s.last_error}
									<p class="mt-1 flex items-center gap-1.5 text-xs text-danger">
										<TriangleAlert size={12} />
										{s.last_error}
									</p>
								{/if}
							</div>
							<div class="flex shrink-0 items-center gap-1">
								<Button
									size="sm"
									variant="ghost"
									title="View programme"
									href="{base}/programmes/{s.programme.id}"
								>
									<Eye size={14} />
								</Button>
								{#if s.status === 'scheduled'}
									<Button
										size="sm"
										variant="ghost"
										title="Reschedule"
										onclick={() => openDialog(s)}
									>
										<Pencil size={14} />
									</Button>
								{/if}
								<Button
									size="sm"
									variant="ghost"
									class="hover:bg-danger/15 hover:text-danger"
									title={cancelTitle(s)}
									onclick={() => {
										confirmTarget = s;
										confirmOpen = true;
									}}
								>
									<Trash2 size={14} />
								</Button>
							</div>
						</article>
					{/each}
				</div>
			</section>
		{/each}
	</div>
{/if}

<Dialog bind:open={modalOpen} title={editing ? 'Reschedule' : 'New schedule'}>
	<div class="space-y-4">
		{#if !editing}
			<div>
				<label class="mb-1 block text-sm text-muted" for="schedProgrammeSearch">Programme</label>
				<Input
					id="schedProgrammeSearch"
					type="search"
					placeholder="Search programmes…"
					bind:value={pickerSearch}
				/>
				<div class="mt-2 max-h-52 overflow-y-auto rounded-md border border-border">
					{#if programmes.loading}
						<Spinner size="sm" />
					{:else if programmes.error}
						<ErrorState error={programmes.error} retry={() => void programmes.load()} compact />
					{:else if pickerMatches.length === 0}
						{#if progList.length === 0}
							<EmptyState
								title="No programmes yet"
								message="A schedule plays a programme - create one first."
								compact
							>
								{#snippet action()}
									<Button size="sm" href="{base}/programmes/new">Create programme</Button>
								{/snippet}
							</EmptyState>
						{:else}
							<EmptyState title="No programmes match" compact />
						{/if}
					{:else}
						{#each pickerMatches as p (p.id)}
							{@const sel = selectedProgramme?.id === p.id}
							<button
								type="button"
								onclick={() => (selectedProgramme = { id: p.id, name: p.name })}
								class="flex w-full items-center justify-between gap-3 border-b border-border px-3 py-2 text-left text-sm last:border-b-0
									{sel ? 'bg-accent/15 text-accent' : 'hover:bg-surface-2'}"
							>
								<span class="truncate">{p.name}</span>
								<span class="shrink-0 font-mono text-xs {sel ? 'text-accent' : 'text-muted'}">
									{runtimes[p.id] ?? 0} min
								</span>
							</button>
						{/each}
					{/if}
				</div>
			</div>
		{:else}
			<div>
				<span class="mb-1 block text-sm text-muted">Programme</span>
				<div class="rounded-md border border-border bg-surface-2 px-3 py-2 text-sm">
					{selectedProgramme?.name}
				</div>
			</div>
		{/if}

		<div class="grid gap-4 sm:grid-cols-2">
			<div>
				<label class="mb-1 block text-sm text-muted" for="schedDateTime">Date &amp; time</label>
				<input
					id="schedDateTime"
					type="datetime-local"
					bind:value={dtValue}
					min={dtMin}
					class="h-9 w-full rounded-md border border-border-strong bg-surface-2 px-3 text-sm text-text focus:border-accent-dim"
				/>
				{#if endHint}
					<p class="mt-1 text-xs text-faint">{endHint}</p>
				{/if}
			</div>
			<div>
				<label class="mb-1 block text-sm text-muted" for="schedTimezone">Timezone</label>
				<Select id="schedTimezone" bind:value={tzValue} class="w-full">
					{#each timezones as tz (tz)}
						<option value={tz}>{tz.replace(/_/g, ' ')}</option>
					{/each}
				</Select>
			</div>
		</div>

		<div>
			<Toggle
				label="Lead-in"
				bind:checked={leadInOn}
				hint="Run commands and hold the title slate before the programme plays"
			/>
			{#if leadInOn}
				<div class="mt-3 flex flex-wrap items-center gap-2">
					<input
						id="schedLeadIn"
						type="number"
						min="0"
						step="1"
						aria-label="Lead-in minutes"
						bind:value={leadInValue}
						class="h-9 w-24 rounded-md border border-border-strong bg-surface-2 px-3 text-sm text-text focus:border-accent-dim"
					/>
					<span class="text-sm text-muted">min before the programme plays</span>
				</div>
				<div class="mt-3">
					<LeadInSteps bind:steps={leadInSteps} length={leadInSeconds} />
				</div>
			{/if}
		</div>

		{#if conflict}
			<div
				class="flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning"
			>
				<TriangleAlert size={14} class="mt-0.5 shrink-0" />
				<span>
					Overlaps <strong>“{conflict.name}”</strong> ({conflict.from}–{conflict.to}) — move it to
					save
				</span>
			</div>
		{/if}

		{#if modalError}
			<p class="text-sm text-danger" role="alert">{modalError}</p>
		{/if}
	</div>

	{#snippet footer()}
		<Button onclick={() => (modalOpen = false)}>Cancel</Button>
		<Button variant="primary" disabled={!canSave || saving} onclick={() => void save()}>
			{saving ? 'Saving…' : editing ? 'Update' : 'Schedule'}
		</Button>
	{/snippet}
</Dialog>

<Dialog bind:open={confirmOpen} title="Cancel schedule" size="md">
	<p class="text-sm">
		Cancel the scheduled screening of
		<strong>“{confirmTarget?.programme.name ?? 'this schedule'}”</strong>?
	</p>
	{#if confirmTarget?.status === 'running'}
		<p class="mt-2 text-xs text-muted">Removing the schedule does not stop playback.</p>
	{/if}

	{#snippet footer()}
		<Button onclick={() => (confirmOpen = false)}>Keep it</Button>
		<Button variant="danger" disabled={removing} onclick={() => void confirmRemove()}>
			{removing ? 'Removing…' : 'Cancel schedule'}
		</Button>
	{/snippet}
</Dialog>
