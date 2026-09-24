/** Background-job plumbing shared by the Sync and Trailers pages: Job payload types, the
 *  WebSocket-filtered JobStream, and unwrapLoose() for the untyped sync/trailer endpoints. */
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

/** REST job serialization (Job.serialize). Log only with include_log. */
export interface ApiJob {
	id: number;
	source_id: number | null;
	operation: string;
	state: string;
	is_active: boolean;
	phase: string | null;
	current: number;
	total: number | null;
	percentage: number;
	current_item: string | null;
	counts: JobCounts;
	created_at: string | null;
	started_at: string | null;
	finished_at: string | null;
	duration_seconds: number | null;
	error?: string | null;
	params?: Record<string, unknown>;
	log?: JobLogEntry[];
}

/** SSE state/progress/complete payload (_job_payload, views/job_sse.py). */
export interface JobEvent {
	job_id: number;
	kind: string;
	source_id: number | null;
	operation: string;
	state: string;
	phase: string | null;
	current: number;
	total: number | null;
	percentage: number;
	current_item: string | null;
	counts: JobCounts;
	error: string | null;
}

/** SSE log payload (_log_payload, views/job_sse.py). */
export interface JobLogEvent {
	job_id: number;
	kind: string;
	source_id: number | null;
	entries: JobLogEntry[];
}

const ACTIVE_STATES = new Set(['queued', 'running', 'cancelling']);

export function jobIsActive(state?: string | null): boolean {
	return ACTIVE_STATES.has(state ?? '');
}

export interface JobStreamHandlers {
	onState?: (p: JobEvent) => void;
	onProgress?: (p: JobEvent) => void;
	onLog?: (p: JobLogEvent) => void;
	onComplete?: (p: JobEvent) => void;
	/** Fires on every (re)connect — pages reconcile against the DB here: a job
	 * that finished while the socket was down never gets a `complete` event on
	 * the new connection (the server only pushes active jobs). */
	onOpen?: () => void;
}

/** A view of the shared socket filtered to one job kind (and optionally one source). */
export class JobStream {
	#kind: string;
	#sourceId?: number;
	#handlers: JobStreamHandlers;
	#unsub: (() => void) | null = null;

	constructor(opts: { kind: string; sourceId?: number }, handlers: JobStreamHandlers = {}) {
		this.#kind = opts.kind;
		this.#sourceId = opts.sourceId;
		this.#handlers = handlers;
	}

	open(): void {
		if (this.#unsub) return;
		this.#unsub = realtime.subscribe({
			channel: 'job',
			onConnect: () => this.#handlers.onOpen?.(),
			onMessage: (msg: RealtimeMessage) => {
				const data = msg.data as JobEvent & JobLogEvent;
				if (data.kind !== this.#kind) return;
				if (this.#sourceId != null && data.source_id !== this.#sourceId) return;
				switch (msg.event) {
					case 'state':
						this.#handlers.onState?.(data);
						break;
					case 'progress':
						this.#handlers.onProgress?.(data);
						break;
					case 'log':
						this.#handlers.onLog?.(data);
						break;
					case 'complete':
						this.#handlers.onComplete?.(data);
						break;
				}
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
