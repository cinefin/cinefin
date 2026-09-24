/**
 * Shared "is a sync running?" signal for the topbar lamp. Rides the sync job
 * stream (subscriber-counted, open only while a consumer is mounted) and
 * reconciles against GET /sync/jobs?active_only=true on every (re)connect,
 * since the stream only carries jobs active while it is open.
 */
import { api } from '$lib/api/client';
import { JobStream, jobIsActive, unwrapLoose, type ApiJob, type JobEvent } from '$lib/jobs';
import { SvelteMap } from 'svelte/reactivity';

interface ActiveSync {
	operation: string;
	state: string;
	percentage: number;
}

class SyncActivityStore {
	#active = new SvelteMap<number, ActiveSync>();

	#subscribers = 0;
	#stream: JobStream | null = null;

	get count(): number {
		return this.#active.size;
	}

	get busy(): boolean {
		return this.#active.size > 0;
	}

	/** Coarse progress of the busiest job, for a tooltip/label. 0 when unknown. */
	get percentage(): number {
		let max = 0;
		for (const j of this.#active.values()) max = Math.max(max, j.percentage || 0);
		return Math.round(max);
	}

	subscribe(): () => void {
		this.#subscribers += 1;
		if (this.#subscribers === 1) this.#open();
		return () => {
			this.#subscribers -= 1;
			if (this.#subscribers === 0) this.#close();
		};
	}

	#open(): void {
		this.#stream = new JobStream(
			{ kind: 'sync' },
			{
				onState: (p) => this.#onEvent(p),
				onProgress: (p) => this.#onEvent(p),
				onComplete: (p) => this.#active.delete(p.job_id),
				onOpen: () => void this.#reconcile()
			}
		);
		this.#stream.open();
	}

	#close(): void {
		this.#stream?.close();
		this.#stream = null;
		this.#active.clear();
	}

	#onEvent(p: JobEvent): void {
		if (jobIsActive(p.state)) {
			this.#active.set(p.job_id, {
				operation: p.operation,
				state: p.state,
				percentage: p.percentage ?? 0
			});
		} else {
			this.#active.delete(p.job_id);
		}
	}

	async #reconcile(): Promise<void> {
		try {
			const data = await unwrapLoose<{ jobs: ApiJob[] }>(
				api.GET('/api/v2/sync/jobs', { params: { query: { active_only: true, limit: 50 } } })
			);
			const seen = new Set<number>();
			for (const j of data.jobs ?? []) {
				seen.add(j.id);
				this.#active.set(j.id, {
					operation: j.operation,
					state: j.state,
					percentage: j.percentage ?? 0
				});
			}
			// Anything tracked but no longer listed finished while the stream was down.
			for (const id of this.#active.keys()) if (!seen.has(id)) this.#active.delete(id);
		} catch {
			// Supplementary — keep whatever the stream tells us.
		}
	}
}

export const syncActivity = new SyncActivityStore();
