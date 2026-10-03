/**
 * Shared "is a job of this kind running?" signal for the topbar lamp. Rides the job stream
 * (subscriber-counted) and reconciles against the active-jobs endpoint on every (re)connect,
 * since the stream only carries jobs active while it is open.
 */
import { api } from '$lib/api/client';
import { JobStream, jobIsActive, unwrapLoose, type ApiJob, type JobEvent } from '$lib/jobs';
import { SvelteMap } from 'svelte/reactivity';
import { refCounted } from './refcount';

export class JobActivityStore {
	/** job id → percentage */
	#active = new SvelteMap<number, number>();
	#kind: 'sync' | 'trailer';
	#fetchActive: () => Promise<ApiJob[]>;

	constructor(kind: 'sync' | 'trailer', fetchActive: () => Promise<ApiJob[]>) {
		this.#kind = kind;
		this.#fetchActive = fetchActive;
	}

	get busy(): boolean {
		return this.#active.size > 0;
	}

	/** Coarse progress of the busiest job. 0 when unknown. */
	get percentage(): number {
		return Math.round(Math.max(0, ...this.#active.values()));
	}

	subscribe = refCounted(() => {
		const onEvent = (p: JobEvent) => {
			if (jobIsActive(p.state)) this.#active.set(p.job_id, p.percentage || 0);
			else this.#active.delete(p.job_id);
		};
		const stream = new JobStream(
			{ kind: this.#kind },
			{
				onState: onEvent,
				onProgress: onEvent,
				onComplete: (p) => this.#active.delete(p.job_id),
				onOpen: () => void this.#reconcile()
			}
		);
		stream.open();
		return () => {
			stream.close();
			this.#active.clear();
		};
	});

	async #reconcile(): Promise<void> {
		try {
			const jobs = await this.#fetchActive();
			this.#active.clear();
			for (const j of jobs) this.#active.set(j.id, j.percentage || 0);
		} catch {
			// Supplementary — keep whatever the stream tells us.
		}
	}
}

export const syncActivity = new JobActivityStore('sync', async () => {
	const data = await unwrapLoose<{ jobs: ApiJob[] }>(
		api.GET('/api/v2/sync/jobs', { params: { query: { active_only: true, limit: 50 } } })
	);
	return data.jobs ?? [];
});
