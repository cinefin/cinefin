// What is coming up, for the remote on standby: the scheduled screenings still to play, soonest
// first, and each programme's features (for its posters and runtime). Background data: a failed
// fetch leaves the last good lists.
import { api, unwrap } from '$lib/api/client';
import { query } from '$lib/api/query.svelte';
import type { components } from '$lib/api/types.gen';

export type Schedule = components['schemas']['ScheduleSchema'];
export type Feature = components['schemas']['MovieInfoSchema'];

export class Upcoming {
	schedules = query(() =>
		unwrap(api.GET('/api/v2/schedules/list', { params: { query: { show_past: false } } }))
	);
	programmes = query(() => unwrap(api.GET('/api/v2/programmes/list')));

	screenings = $derived(
		((this.schedules.data?.schedules ?? []) as Schedule[])
			.filter((s) => s.status === 'scheduled')
			.sort((a, b) => new Date(a.play_time).getTime() - new Date(b.play_time).getTime())
	);

	#byId = $derived(new Map((this.programmes.data?.programmes ?? []).map((p) => [p.id, p])));

	features(programmeId: number): Feature[] {
		return this.#byId.get(programmeId)?.movies ?? [];
	}

	runtime(programmeId: number): number {
		return Math.round(this.#byId.get(programmeId)?.total_runtime ?? 0);
	}

	/** Keep both fresh while the remote is open. */
	start(): () => void {
		const stops = [
			this.schedules.live({ everyMs: 60_000, keys: ['schedules', 'programmes'] }),
			this.programmes.invalidatesOn(['programmes'])
		];
		return () => stops.forEach((stop) => stop());
	}
}
