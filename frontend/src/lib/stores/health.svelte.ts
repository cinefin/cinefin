/**
 * Shared system health report. /system/health is the app's slowest read (it probes the printer,
 * the agent and the disks), so it refreshes every 60 s while subscribed, plus on invalidation.
 */
import { api, unwrap } from '$lib/api/client';
import { Query } from '$lib/api/query.svelte';
import type { components } from '$lib/api/types.gen';
import { refCounted } from './refcount';

export type HealthCheck = components['schemas']['HealthCheckSchema'];
type HealthReport = components['schemas']['HealthReportSchema'];

const RANK: Record<string, number> = { error: 0, warn: 1 };

class HealthStore {
	#query = new Query<HealthReport>(() => unwrap(api.GET('/api/v2/system/health')));
	rechecking = $state<string | null>(null);

	get report(): HealthReport | undefined {
		return this.#query.data;
	}

	get checks(): HealthCheck[] {
		return this.#query.data?.checks ?? [];
	}

	/** Failing checks, errors first. */
	get problems(): HealthCheck[] {
		return this.checks
			.filter((c) => c.status === 'error' || c.status === 'warn')
			.sort((a, b) => RANK[a.status] - RANK[b.status]);
	}

	check(key: string): HealthCheck | null {
		return this.checks.find((c) => c.key === key) ?? null;
	}

	subscribe = refCounted(() => {
		void this.#query.load();
		return this.#query.live({ everyMs: 60_000, keys: ['health'] });
	});

	refresh(): Promise<void> {
		return this.#query.refresh();
	}

	/** Re-run one check and swap its result into the report. */
	async recheck(key: string): Promise<void> {
		this.rechecking = key;
		try {
			const fresh = await unwrap(
				api.POST('/api/v2/system/health/{key}', { params: { path: { key } } })
			);
			const report = this.#query.data;
			if (fresh && report) {
				this.#query.data = {
					...report,
					checks: report.checks.map((c) => (c.key === key ? fresh : c))
				};
			}
		} finally {
			this.rechecking = null;
		}
	}
}

export const health = new HealthStore();
