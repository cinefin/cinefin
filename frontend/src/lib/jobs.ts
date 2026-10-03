/** Background-job plumbing: Job payload types, the WebSocket-filtered JobStream, and
 *  unwrapLoose() for the untyped sync/trailer endpoints. */
import { toApiError } from '$lib/api/client';
import { realtime, type RealtimeMessage } from '$lib/realtime.svelte';

export interface JobLogEntry {
	ts: string;
	level: string;
	message: string;
}

/** Job.counts JSON — numeric buckets plus the run's `changes` receipt. */
export interface JobCounts {
	added?: number;
	updated?: number;
	skipped?: number;
	removed?: number;
	unmatched?: number;
	failed?: number;
	changes?: {
		added?: string[];
		updated?: string[];
		removed?: string[];
		unmatched?: string[];
	};
	[extra: string]: unknown;
}

/** Fields shared by the REST job and its live events. */
interface JobProgressFields {
	source_id: number | null;
	operation: string;
	state: string;
	phase: string | null;
	current: number;
	total: number | null;
	percentage: number;
	current_item: string | null;
	counts: JobCounts;
}

/** REST job serialization (Job.serialize). Log only with include_log. */
export interface ApiJob extends JobProgressFields {
	id: number;
	is_active: boolean;
	created_at: string | null;
	started_at: string | null;
	finished_at: string | null;
	duration_seconds: number | null;
	error?: string | null;
	params?: Record<string, unknown>;
	log?: JobLogEntry[];
}

/** SSE state/progress/complete payload (_job_payload, views/job_sse.py). */
export interface JobEvent extends JobProgressFields {
	job_id: number;
	kind: string;
	error: string | null;
}

const ACTIVE_STATES = new Set(['queued', 'running', 'cancelling']);

export function jobIsActive(state?: string | null): boolean {
	return ACTIVE_STATES.has(state ?? '');
}

export interface JobStreamHandlers {
	onState?: (p: JobEvent) => void;
	onProgress?: (p: JobEvent) => void;
	onComplete?: (p: JobEvent) => void;
	/** Fires on every (re)connect — reconcile against the DB here: a job that finished while the
	 * socket was down never gets a `complete` event (the server only pushes active jobs). */
	onOpen?: () => void;
}

/** A view of the shared socket filtered to one job kind. */
export class JobStream {
	#kind: string;
	#handlers: JobStreamHandlers;
	#unsub: (() => void) | null = null;

	constructor(opts: { kind: string }, handlers: JobStreamHandlers = {}) {
		this.#kind = opts.kind;
		this.#handlers = handlers;
	}

	open(): void {
		if (this.#unsub) return;
		const h = this.#handlers;
		const byEvent: Record<string, ((p: JobEvent) => void) | undefined> = {
			state: h.onState,
			progress: h.onProgress,
			complete: h.onComplete
		};
		this.#unsub = realtime.subscribe({
			channel: 'job',
			onConnect: () => h.onOpen?.(),
			onMessage: (msg: RealtimeMessage) => {
				const data = msg.data as JobEvent;
				if (data.kind === this.#kind) byEvent[msg.event as string]?.(data);
			}
		});
	}

	close(): void {
		this.#unsub?.();
		this.#unsub = null;
	}
}

/**
 * unwrap() for endpoints whose generated response type is empty (sync/trailer routers return
 * plain `ok(data)` dicts with no schema). The caller supplies T from the backend serializer.
 */
export async function unwrapLoose<T>(
	pending: PromiseLike<{ data?: unknown; error?: unknown; response: Response }>
): Promise<T> {
	const result = await pending;
	if (result.error !== undefined || result.data === undefined || result.data === null) {
		throw toApiError(result.error, result.response);
	}
	return (result.data as { data?: unknown }).data as T;
}
