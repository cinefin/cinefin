import { api, unwrap } from '$lib/api/client';
import { query, type Query } from '$lib/api/query.svelte';
import { invalidate } from '$lib/invalidate';
import { JobStream, jobIsActive, unwrapLoose, type JobEvent } from '$lib/jobs';
import type { TrailerStatistics } from '$lib/api/refinements';
import type { components } from '$lib/api/types.gen';

export type Schedule = components['schemas']['ScheduleSchema'];
export type ProgrammeListItem = components['schemas']['ProgrammeListItemSchema'];
export type MovieListItem = components['schemas']['MovieListItemSchema'];

interface SyncJobBrief {
	state?: string;
	is_active?: boolean;
	current?: number;
	percentage?: number;
}

interface SyncSourceBrief {
	id: number;
	name: string;
	enabled: boolean;
	last_sync: string | null;
}

interface SourceList {
	sources: SyncSourceBrief[];
}

export class DashboardData {
	stats = query(() => unwrap(api.GET('/api/v2/movies/stats')));
	schedules = query(() =>
		unwrap(api.GET('/api/v2/schedules/list', { params: { query: { show_past: false } } }))
	);
	programmes = query(() => unwrap(api.GET('/api/v2/programmes/list')));
	recentMovies = query(() =>
		unwrap(
			api.GET('/api/v2/movies/list', {
				params: { query: { per_page: 30, sort: 'date_added', order: 'desc' } }
			})
		)
	);
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

	movies = $derived(this.recentMovies.data?.items ?? []);

	get source(): SyncSourceBrief | null {
		return this.sources.data?.sources[0] ?? null;
	}

	get lastSync(): string | null {
		const stamps = (this.sources.data?.sources ?? []).map((s) => s.last_sync).filter(Boolean);
		return (stamps.sort().at(-1) as string | undefined) ?? null;
	}

	start(): () => void {
		const stops = [
			this.schedules.invalidatesOn(['schedules', 'programmes']),
			this.sources.invalidatesOn(['sync']),
			this.stats.invalidatesOn(['movies', 'sync']),
			this.programmes.invalidatesOn(['programmes']),
			this.recentMovies.invalidatesOn(['movies', 'sync']),
			this.trailers.invalidatesOn(['trailers', 'sync']),
			this.#watchSync()
		];
		return () => stops.forEach((stop) => stop());
	}

	programmeFor(id: number | undefined | null): ProgrammeListItem | null {
		if (id == null) return null;
		return this.programmes.data?.programmes.find((p) => p.id === id) ?? null;
	}

	#watchSync(): () => void {
		const adopt = (p: JobEvent) => {
			this.activeSync = jobIsActive(p.state)
				? { state: p.state, is_active: true, current: p.current, percentage: p.percentage }
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
	return new Date(when).toDateString() === new Date().toDateString();
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
