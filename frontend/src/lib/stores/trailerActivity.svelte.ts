/**
 * Shared "is a trailer job running?" signal for the topbar lamp — the trailer
 * twin of syncActivity. Reconciles against GET /trailers/jobs/current, which
 * runs one at a time.
 */
import { api } from '$lib/api/client';
import { JobStream, jobIsActive, unwrapLoose, type ApiJob, type JobEvent } from '$lib/jobs';
import { SvelteMap } from 'svelte/reactivity';

interface ActiveJob {
	operation: string;
	state: string;
	percentage: number;
}

class TrailerActivityStore {
	#active = new SvelteMap<number, ActiveJob>();
	#subscribers = 0;
	#stream: JobStream | null = null;

	get busy(): boolean {
		return this.#active.size > 0;
	}

	/** Coarse progress of the busiest job, for the lamp label. 0 when unknown. */
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
			{ kind: 'trailer' },
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
			const data = await unwrapLoose<{ job: ApiJob | null }>(
				api.GET('/api/v2/trailers/jobs/current')
			);
			const job = data.job;
			this.#active.clear();
			if (job && job.is_active) {
				this.#active.set(job.id, {
					operation: job.operation,
					state: job.state,
					percentage: job.percentage ?? 0
				});
			}
		} catch {
			// Supplementary — keep whatever the stream tells us.
		}
	}
}

export const trailerActivity = new TrailerActivityStore();
