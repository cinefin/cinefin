import { api } from '$lib/api/client';
import { JobStream, jobIsActive, unwrapLoose, type ApiJob, type JobEvent } from '$lib/jobs';
import { showToast, toastFailure } from '$lib/toast.svelte';

type Pending = PromiseLike<{ data?: unknown; error?: unknown; response: Response }>;

/**
 * The trailer job on the trailers page (they run one at a time): the job last loaded or
 * started, whether one is running, and the live head JobProgress shows, kept current from the
 * job stream.
 */
export class TrailerJob {
	job = $state<ApiJob | null>(null);
	active = $state(false);
	/** What JobProgress shows: the job as loaded, then its stream events. */
	head = $state<ApiJob | JobEvent | null>(null);
	headId: number | null = null;
	#oncomplete: (p: JobEvent) => void;

	constructor(oncomplete: (p: JobEvent) => void) {
		this.#oncomplete = oncomplete;
	}

	#show(j: ApiJob) {
		this.job = this.head = j;
		this.headId = j.id;
	}

	/** Load the current job, if any. */
	async reattach() {
		try {
			const { job } = await unwrapLoose<{ job: ApiJob | null }>(
				api.GET('/api/v2/trailers/jobs/current')
			);
			if (job) {
				this.#show(job);
				this.active = job.is_active;
			}
		} catch {
			/* no current job */
		}
	}

	/** Follow the job stream (from an $effect); returns the stop function. */
	follow(): () => void {
		void this.reattach();
		const onEvent = (p: JobEvent) => {
			this.active = jobIsActive(p.state);
			// The head follows its job, or switches to a *new active* one (never a stale terminal one).
			if (p.job_id === this.headId || this.active) {
				this.headId = p.job_id;
				this.head = p;
			}
			if (this.active && this.job?.id !== p.job_id) void this.reattach();
		};
		const stream = new JobStream(
			{ kind: 'trailer' },
			{
				onState: onEvent,
				onProgress: onEvent,
				onComplete: (p) => {
					if (p.job_id === this.headId) this.head = p;
					if (!this.active && this.job && p.job_id !== this.job.id) return;
					this.active = false;
					this.#oncomplete(p);
				},
				onOpen: () => void this.reattach()
			}
		);
		stream.open();
		return () => stream.close();
	}

	/** Start a job; one already running is attached to instead. */
	async start(run: () => Pending) {
		try {
			this.#show((await unwrapLoose<{ job: ApiJob }>(run())).job);
			this.active = true;
			showToast('Job started', 'success');
		} catch (e) {
			if (!/already running/i.test(e instanceof Error ? e.message : String(e))) {
				return toastFailure('Failed', e);
			}
			showToast('A trailer job is already running', 'info');
			await this.reattach();
		}
	}
}
