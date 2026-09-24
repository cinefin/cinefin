<script lang="ts">
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
		Film,
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
	import Dialog from '$lib/components/ui/Dialog.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import ErrorState from '$lib/components/ui/ErrorState.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Select from '$lib/components/ui/Select.svelte';
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

	const all = $derived((schedules.data?.schedules ?? []) as Schedule[]);

	const posters = $derived.by(() => {
		const map: Record<number, string> = {};
		for (const p of programmes.data?.programmes ?? []) {
			const featured = p.movies.find((m) => m.thumbnail_url);
			if (featured?.thumbnail_url) map[p.id] = featured.thumbnail_url;
		}
		return map;
	});
	const runtimes = $derived.by(() => {
		const map: Record<number, number> = {};
		for (const p of programmes.data?.programmes ?? []) map[p.id] = Math.round(p.total_runtime);
		return map;
	});

	const STATUSES = [
		{ value: '', label: 'All' },
		{ value: 'scheduled', label: 'Scheduled' },
		{ value: 'running', label: 'Running' },
		{ value: 'completed', label: 'Completed' },
		{ value: 'cancelled', label: 'Cancelled' },
		{ value: 'failed', label: 'Failed' },
		{ value: 'missed', label: 'Missed' }
	];

	let statusFilter = $state('');
	let showPast = $state(false);
	let view = $state<'list' | 'calendar'>(
		localStorage.getItem('sched.view') === 'calendar' ? 'calendar' : 'list'
	);
	function setView(v: 'list' | 'calendar') {
		view = v;
		localStorage.setItem('sched.view', v);
	}

	const statusCounts = $derived.by(() => {
		const c: Record<string, number> = {};
		for (const s of all) c[s.status] = (c[s.status] ?? 0) + 1;
		return c;
	});
	const activeCount = $derived((statusCounts.scheduled ?? 0) + (statusCounts.running ?? 0));
	const todayCount = $derived.by(() => {
		const today = new Date();
		today.setHours(0, 0, 0, 0);
		const tomorrow = new Date(today);
		tomorrow.setDate(tomorrow.getDate() + 1);
		return all.filter((s) => {
			const d = new Date(s.start_time);
			return d >= today && d < tomorrow;
		}).length;
	});

	function endMs(s: Schedule): number {
		if (s.end_time) return new Date(s.end_time).getTime();
		return new Date(s.start_time).getTime() + (s.runtime || 0) * 60000;
	}

	const visible = $derived.by(() => {
		const now = Date.now();
		return all
			.filter((s) => {
				if (statusFilter && s.status !== statusFilter) return false;
				if (!showPast && endMs(s) < now) return false;
				return true;
			})
			.sort((a, b) => new Date(a.start_time).getTime() - new Date(b.start_time).getTime());
	});

	const dayGroups = $derived.by(() => {
		const keys: string[] = [];
		const byDay = new Map<string, Schedule[]>();
		for (const s of visible) {
			const key = new Date(s.start_time).toDateString();
			if (!byDay.has(key)) {
				byDay.set(key, []);
				keys.push(key);
			}
			byDay.get(key)!.push(s);
		}
		return keys.map((key) => ({ key, items: byDay.get(key)! }));
	});

	const filtersActive = $derived(Boolean(statusFilter) || showPast);

	const MAX_CHIPS = 3;
	function firstOfMonth(d: Date): Date {
		return new Date(d.getFullYear(), d.getMonth(), 1);
	}
	let calMonth = $state(firstOfMonth(new Date()));
	function shiftMonth(delta: number) {
		calMonth = new Date(calMonth.getFullYear(), calMonth.getMonth() + delta, 1);
	}

	const calTitle = $derived(
		calMonth.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })
	);

	interface CalCell {
		day: Date;
		outside: boolean;
		today: boolean;
		items: Schedule[];
	}

	// 6-week Monday-first grid; the status filter applies, "Show past" does not.
	const calCells = $derived.by((): CalCell[] => {
		const byDay = new Map<string, Schedule[]>();
		for (const s of all) {
			if (statusFilter && s.status !== statusFilter) continue;
			const key = new Date(s.start_time).toDateString();
			if (!byDay.has(key)) byDay.set(key, []);
			byDay.get(key)!.push(s);
		}
		const firstWeekday = (calMonth.getDay() + 6) % 7; // Monday = 0
		const gridStart = new Date(calMonth.getFullYear(), calMonth.getMonth(), 1 - firstWeekday);
		const todayKey = new Date().toDateString();
		const thisMonth = calMonth.getMonth();

		const cells: CalCell[] = [];
		for (let i = 0; i < 42; i++) {
			const day = new Date(gridStart.getFullYear(), gridStart.getMonth(), gridStart.getDate() + i);
			const key = day.toDateString();
			cells.push({
				day,
				outside: day.getMonth() !== thisMonth,
				today: key === todayKey,
				items: (byDay.get(key) ?? [])
					.slice()
					.sort((a, b) => new Date(a.start_time).getTime() - new Date(b.start_time).getTime())
			});
		}
		return cells;
	});

	const statusVariant: Record<string, 'default' | 'accent' | 'success' | 'warning' | 'danger'> = {
		scheduled: 'default',
		running: 'accent',
		completed: 'success',
		cancelled: 'warning',
		failed: 'danger',
		missed: 'warning'
	};

	const calChipClass: Record<string, string> = {
		scheduled: 'bg-surface-3 text-text',
		running: 'bg-accent/20 text-accent',
		completed: 'bg-success/15 text-success',
		cancelled: 'bg-warning/15 text-warning',
		failed: 'bg-danger/15 text-danger',
		missed: 'bg-warning/15 text-warning'
	};

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
			const p: Record<string, string> = {};
			dtf.formatToParts(epochMs).forEach((part) => {
				p[part.type] = part.value;
			});
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

	function defaultDateTime(): string {
		const d = new Date();
		d.setMinutes(d.getMinutes() + 5 - (d.getMinutes() % 5), 0, 0); // round up to next 5 min
		d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
		return d.toISOString().slice(0, 16);
	}

	function localNow(): string {
		const d = new Date();
		d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
		return d.toISOString().slice(0, 16);
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
	let mode = $state<'create' | 'edit'>('create');
	let editing = $state<Schedule | null>(null);
	let selectedProgramme = $state<{ id: number; name: string } | null>(null);
	let pickerSearch = $state('');
	let dtValue = $state('');
	let dtMin = $state('');
	let tzValue = $state(browserZone);
	let saving = $state(false);
	let modalError = $state<string | null>(null);

	function openCreate(preselect: ProgrammeListItem | null = null) {
		mode = 'create';
		editing = null;
		selectedProgramme = preselect ? { id: preselect.id, name: preselect.name } : null;
		pickerSearch = '';
		dtValue = defaultDateTime();
		dtMin = localNow();
		modalError = null;
		tzValue = browserZone;
		modalOpen = true;
	}

	function openEdit(s: Schedule) {
		mode = 'edit';
		editing = s;
		selectedProgramme = { id: s.programme.id, name: s.programme.name };
		const start = new Date(s.start_time);
		start.setMinutes(start.getMinutes() - start.getTimezoneOffset());
		dtValue = start.toISOString().slice(0, 16);
		dtMin = localNow();
		modalError = null;
		tzValue = browserZone;
		modalOpen = true;
	}

	const pickerMatches = $derived.by(() => {
		const q = pickerSearch.trim().toLowerCase();
		const list = (programmes.data?.programmes ?? []) as ProgrammeListItem[];
		return q ? list.filter((p) => p.name.toLowerCase().includes(q)) : list;
	});

	const canSave = $derived(Boolean(dtValue) && Boolean(selectedProgramme));

	const currentRuntime = $derived.by(() => {
		if (mode === 'edit' && editing) {
			return editing.runtime || runtimes[editing.programme.id] || 0;
		}
		return selectedProgramme ? runtimes[selectedProgramme.id] || 0 : 0;
	});

	// "Ends ~21:47" hint. Wall-clock arithmetic in the terms the start time is entered in.
	const endHint = $derived.by(() => {
		const startWall = parseWallClock(dtValue);
		const runtime = currentRuntime;
		if (startWall == null || !runtime || !Number.isFinite(runtime)) return '';
		const end = new Date(startWall + Math.round(runtime) * 60000);
		const pad = (n: number) => String(n).padStart(2, '0');
		const time = `${pad(end.getUTCHours())}:${pad(end.getUTCMinutes())}`;
		const sameDay =
			dtValue.slice(0, 10) ===
			`${end.getUTCFullYear()}-${pad(end.getUTCMonth() + 1)}-${pad(end.getUTCDate())}`;
		return `Ends ~${time}${sameDay ? '' : ' (next day)'}`;
	});

	// Non-blocking heads-up when the slot overlaps another scheduled/running screening.
	const conflict = $derived.by(() => {
		if (!dtValue || !selectedProgramme) return null;
		const runtime = currentRuntime;
		if (!runtime) return null; // unknown runtime: don't guess
		const start = wallClockToEpoch(dtValue, tzValue);
		if (start == null) return null;
		const end = start + Math.round(runtime) * 60000;

		const clash = all.find((s) => {
			if (mode === 'edit' && editing && s.id === editing.id) return false;
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

	async function save() {
		if (!canSave || saving) return;
		saving = true;
		modalError = null;
		try {
			if (mode === 'edit' && editing) {
				await unwrap(
					api.PUT('/api/v2/schedules/{schedule_id}', {
						params: { path: { schedule_id: editing.id } },
						body: { start_time: dtValue, timezone: tzValue }
					})
				);
				notice.show('success', 'Schedule updated');
			} else {
				await unwrap(
					api.POST('/api/v2/schedules/create', {
						body: { programme_id: selectedProgramme!.id, start_time: dtValue, timezone: tzValue }
					})
				);
				notice.show('success', 'Schedule created');
			}
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

	function askRemove(s: Schedule) {
		confirmTarget = s;
		confirmOpen = true;
	}

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
		const wanted = (programmes.data.programmes ?? []).find((p) => p.id === deepLinkId);
		deepLinkId = null;
		void goto(`${base}/schedules`, { replaceState: true }); // don't reopen on refresh
		openCreate(wanted ?? null);
	});
</script>

<svelte:head><title>Schedules - Cinefin</title></svelte:head>

<div class="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2">
	<h1 class="text-lg font-semibold">Schedules</h1>
	<div class="mr-auto flex items-center gap-4 text-xs text-muted">
		<span>Total <span class="font-mono text-text">{all.length}</span></span>
		<span>Active <span class="font-mono text-text">{activeCount}</span></span>
		<span>Today <span class="font-mono text-text">{todayCount}</span></span>
	</div>
	<Button variant="primary" onclick={() => openCreate()}>
		<Plus size={14} /> New schedule
	</Button>
</div>

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
			<button
				type="button"
				title="List view"
				aria-label="List view"
				aria-pressed={view === 'list'}
				onclick={() => setView('list')}
				class="flex h-7 w-8 items-center justify-center
					{view === 'list' ? 'bg-surface-3 text-accent' : 'bg-surface-2 text-muted hover:text-text'}"
			>
				<List size={14} />
			</button>
			<button
				type="button"
				title="Calendar view"
				aria-label="Calendar view"
				aria-pressed={view === 'calendar'}
				onclick={() => setView('calendar')}
				class="flex h-7 w-8 items-center justify-center border-l border-border-strong
					{view === 'calendar' ? 'bg-surface-3 text-accent' : 'bg-surface-2 text-muted hover:text-text'}"
			>
				<Calendar size={14} />
			</button>
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
			<div class="text-sm font-medium">{calTitle}</div>
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
								class="flex items-baseline gap-1 truncate rounded-xs px-1 py-0.5 text-[0.65rem] leading-tight {calChipClass[
									s.status
								] ?? 'bg-surface-3 text-text'}"
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
		>
			{#snippet action()}
				<Button variant="primary" onclick={() => openCreate()}>
					<Plus size={14} /> New schedule
				</Button>
			{/snippet}
		</EmptyState>
	{/if}
{:else}
	<div class="space-y-6">
		{#each dayGroups as group (group.key)}
			<section>
				<div class="mb-2 flex items-baseline gap-2">
					<h2 class="text-[0.8rem] font-medium text-muted">
						{dayLabel(new Date(group.key))}
					</h2>
					<span class="font-mono text-xs text-faint">{group.items.length}</span>
				</div>
				<div class="space-y-2">
					{#each group.items as s (s.id)}
						{@const start = new Date(s.start_time)}
						{@const end = new Date(endMs(s))}
						{@const poster = posters[s.programme.id]}
						{@const rel = relTime(s)}
						<article
							class="flex items-center gap-4 rounded-lg border border-border bg-surface-1 p-3"
						>
							<div class="w-16 shrink-0 text-right">
								<div class="font-mono text-sm font-semibold">{formatClock(start)}</div>
								<div class="font-mono text-xs text-faint">→ {formatClock(end)}</div>
							</div>
							<div
								class="h-16 w-11 shrink-0 overflow-hidden rounded-sm border border-border bg-surface-2"
							>
								{#if poster}
									<img src={poster} alt="" loading="lazy" class="h-full w-full object-cover" />
								{:else}
									<div class="flex h-full items-center justify-center text-faint">
										<Film size={14} />
									</div>
								{/if}
							</div>
							<div class="min-w-0 flex-1">
								<a
									href="{base}/programmes/{s.programme.id}"
									title="Open programme"
									class="block truncate text-sm font-medium hover:text-accent"
								>
									{s.programme.name}
								</a>
								<div class="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
									<Badge variant={statusVariant[s.status] ?? 'default'}>{s.status}</Badge>
									<span class="inline-flex items-center gap-1">
										<Clock size={12} />
										{s.runtime} min
									</span>
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
									<Button size="sm" variant="ghost" title="Reschedule" onclick={() => openEdit(s)}>
										<Pencil size={14} />
									</Button>
								{/if}
								<Button
									size="sm"
									variant="ghost"
									class="hover:bg-danger/15 hover:text-danger"
									title={cancelTitle(s)}
									onclick={() => askRemove(s)}
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

<Dialog bind:open={modalOpen} title={mode === 'edit' ? 'Reschedule' : 'New schedule'}>
	<div class="space-y-4">
		{#if mode === 'create'}
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
						{#if (programmes.data?.programmes ?? []).length === 0}
							<EmptyState
								title="No programmes yet"
								message="A schedule plays a programme - create one first."
								compact
							>
								{#snippet action()}
									<Button size="sm" href="{base}/programmes/create">Create programme</Button>
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

		{#if conflict}
			<div
				class="flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning"
			>
				<TriangleAlert size={14} class="mt-0.5 shrink-0" />
				<span>
					Overlaps with <strong>“{conflict.name}”</strong> at {conflict.from}-{conflict.to}
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
			{saving ? 'Saving…' : mode === 'edit' ? 'Update' : 'Schedule'}
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
