import { api, unwrap } from '$lib/api/client';
import { query, type Query } from '$lib/api/query.svelte';
import { invalidate } from '$lib/invalidate';
import { JobStream, jobIsActive, unwrapLoose, type JobEvent } from '$lib/jobs';
import type { TrailerStatistics } from '$lib/api/refinements';
import type { components } from '$lib/api/types.gen';

export type Schedule = components['schemas']['ScheduleSchema'];
export type ProgrammeListItem = components['schemas']['ProgrammeListItemSchema'];
export type MovieListItem = components['schemas']['MovieListItemSchema'];
export type HealthReport = components['schemas']['HealthReportSchema'];
export type HealthCheck = components['schemas']['HealthCheckSchema'];

interface SyncJobBrief {
	id?: number;
	state?: string;
	is_active?: boolean;
	current?: number;
	total?: number | null;
	percentage?: number;
}

export interface SyncSourceBrief {
	id: number;
	name: string;
	sync_type: string;
	enabled: boolean;
	last_sync: string | null;
	is_syncing: boolean;
	active_job: { percentage?: number; phase?: string | null; current?: number } | null;
	last_job: { state?: string; finished_at?: string | null; error?: string | null } | null;
}

interface SourceList {
	sources: SyncSourceBrief[];
	count: number;
}

export class DashboardData {
	runner = query(() => unwrap(api.GET('/api/v2/schedules/runner')));
	stats = query(() => unwrap(api.GET('/api/v2/movies/stats')));
	schedules = query(() =>
		unwrap(api.GET('/api/v2/schedules/list', { params: { query: { show_past: false } } }))
	);
	programmes = query(() => unwrap(api.GET('/api/v2/programmes/list')));
	recentMovies = query(() =>
		unwrap(
			api.GET('/api/v2/movies/list', {
				params: { query: { per_page: 12, sort: 'date_added', order: 'desc' } }
			})
		)
	);
	health: Query<HealthReport> = query(() => unwrap(api.GET('/api/v2/system/health')));
	trailers: Query<TrailerStatistics> = query(async () => {
		const data = await unwrap(api.GET('/api/v2/trailers/stats'));
		return (data?.statistics ?? {}) as unknown as TrailerStatistics;
	});
	sources: Query<SourceList> = query(() =>
		unwrapLoose<SourceList>(api.GET('/api/v2/sync/sources'))
	);

	/** The running library sync, if any — a first run lands here mid-crawl. */
	activeSync = $state<SyncJobBrief | null>(null);

	upcoming = $derived(
		[...(this.schedules.data?.schedules ?? [])].sort(
			(a, b) => new Date(a.start_time).getTime() - new Date(b.start_time).getTime()
		) as Schedule[]
	);

	nextScreening = $derived<Schedule | null>(this.upcoming[0] ?? null);

	recentProgrammes = $derived(
		[...(this.programmes.data?.programmes ?? [])].sort(
			(a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
		)
	);

	movies = $derived(this.recentMovies.data?.items ?? []);

	get overallHealth(): 'ok' | 'warn' | 'error' | 'unknown' {
		const o = this.health.data?.overall;
		return o === 'ok' || o === 'warn' || o === 'error' ? o : 'unknown';
	}

	get problems(): HealthCheck[] {
		const rank: Record<string, number> = { error: 0, warn: 1 };
		return (this.health.data?.checks ?? [])
			.filter((c) => c.status === 'error' || c.status === 'warn')
			.sort((a, b) => (rank[a.status] ?? 2) - (rank[b.status] ?? 2));
	}

	get disk(): HealthCheck | null {
		return this.health.data?.checks.find((c) => c.key.includes('disk')) ?? null;
	}

	get syncing(): SyncSourceBrief | null {
		return this.sources.data?.sources.find((s) => s.is_syncing) ?? null;
	}

	get lastSync(): string | null {
		const stamps = (this.sources.data?.sources ?? [])
			.map((s) => s.last_sync)
			.filter(Boolean) as string[];
		return stamps.length ? (stamps.sort().at(-1) ?? null) : null;
	}

	start(): () => void {
		const stops = [
			this.runner.invalidatesOn(['runner']),
			this.schedules.invalidatesOn(['schedules', 'programmes']),
			this.sources.invalidatesOn(['sync']),
			this.health.invalidatesOn(['health']),
			this.stats.invalidatesOn(['movies', 'sync']),
			this.programmes.invalidatesOn(['programmes']),
			this.recentMovies.invalidatesOn(['movies', 'sync']),
			this.trailers.invalidatesOn(['trailers', 'sync']),
			this.#watchSync()
		];
		return () => stops.forEach((stop) => stop());
	}

	refreshLibrary() {
		invalidate(['movies']);
	}

	programmeFor(id: number | undefined | null): ProgrammeListItem | null {
		if (id == null) return null;
		return this.programmes.data?.programmes.find((p) => p.id === id) ?? null;
	}

	posterForProgramme(id: number | undefined | null): string | null {
		const prog = this.programmeFor(id);
		return prog?.movies.find((m) => m.thumbnail_url)?.thumbnail_url ?? null;
	}

	#watchSync(): () => void {
		const adopt = (p: JobEvent) => {
			this.activeSync = jobIsActive(p.state)
				? {
						id: p.job_id,
						state: p.state,
						is_active: true,
						current: p.current,
						total: p.total,
						percentage: p.percentage
					}
				: null;
		};
		const stream = new JobStream(
			{ kind: 'sync' },
			{
				onState: adopt,
				onProgress: adopt,
				onComplete: () => {
					this.activeSync = null;
					invalidate(['movies', 'sync']);
				},
				onOpen: () => void this.#reconcileSync()
			}
		);
		stream.open();
		return () => stream.close();
	}

	async #reconcileSync(): Promise<void> {
		try {
			const res = await api.GET('/api/v2/sync/jobs', {
				params: { query: { active_only: true, limit: 5 } }
			});
			const payload = res.data as unknown as { data?: { jobs?: SyncJobBrief[] } } | undefined;
			this.activeSync = (payload?.data?.jobs ?? []).find((j) => j.is_active) ?? null;
		} catch {
			/* keep the last state */
		}
	}
}

export interface PlayoutBadge {
	label: string;
	/** The one loud state: a solid tally block rather than a lamp. */
	tally?: boolean;
	colour: 'green' | 'amber' | 'neutral' | 'red';
}

const STATE_BADGES: Record<string, PlayoutBadge> = {
	running: { label: 'On air', tally: true, colour: 'red' },
	pre_show: { label: 'Pre-show', tally: true, colour: 'red' },
	paused: { label: 'Paused', colour: 'amber' },
	loaded: { label: 'Cued', colour: 'green' }
};

export function playoutBadge(state: string | undefined | null): PlayoutBadge {
	if (!state) return { label: 'Idle', colour: 'neutral' };
	return STATE_BADGES[state] ?? { label: state, colour: 'neutral' };
}

export function itemProgress(
	playback: { position?: number; duration?: number; percentage?: number } | null | undefined
): number {
	if (!playback) return 0;
	const clamp = (n: number) => Math.max(0, Math.min(100, n));
	if (typeof playback.percentage === 'number') return clamp(playback.percentage);
	if (playback.duration) return clamp(((playback.position ?? 0) / playback.duration) * 100);
	return 0;
}

// "in 4 min" / "in 2 h 10" / "in 3 days"; past a day it stops counting hours.
export function untilLabel(when: Date | string): string {
	const then = typeof when === 'string' ? new Date(when) : when;
	const mins = Math.round((then.getTime() - Date.now()) / 60000);
	if (mins <= 0) return 'now';
	if (mins < 60) return `in ${mins} min`;
	if (mins < 1440) {
		const h = Math.floor(mins / 60);
		const rest = mins % 60;
		return rest ? `in ${h} h ${rest}` : `in ${h} h`;
	}
	const days = Math.round(mins / 1440);
	return days === 1 ? 'in a day' : `in ${days} days`;
}

export function isToday(when: Date | string): boolean {
	const d = typeof when === 'string' ? new Date(when) : when;
	const now = new Date();
	return (
		d.getFullYear() === now.getFullYear() &&
		d.getMonth() === now.getMonth() &&
		d.getDate() === now.getDate()
	);
}

export const SCHEDULE_BADGE: Record<
	string,
	'default' | 'accent' | 'success' | 'warning' | 'danger'
> = {
	pending: 'default',
	scheduled: 'default',
	running: 'accent',
	completed: 'success',
	failed: 'danger',
	cancelled: 'warning',
	missed: 'warning'
};
