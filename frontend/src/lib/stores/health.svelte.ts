/**
 * Shared system health report — the topbar health menu and the dashboard read the
 * same one. /system/health is the app's slowest read (it probes the printer, the
 * agent and the disks), so it refreshes every 60 s while a consumer is mounted,
 * plus on the realtime "health" invalidation. Subscribe from an $effect.
 */
import { api, unwrap } from '$lib/api/client';
import { Query } from '$lib/api/query.svelte';
import type { components } from '$lib/api/types.gen';

export type HealthCheck = components['schemas']['HealthCheckSchema'];
type HealthReport = components['schemas']['HealthReportSchema'];

const RANK: Record<string, number> = { error: 0, warn: 1 };

class HealthStore {
	#query = new Query<HealthReport>(() => unwrap(api.GET('/api/v2/system/health')));
	#subscribers = 0;
	#stop: (() => void) | null = null;
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

	subscribe(): () => void {
		if (++this.#subscribers === 1) {
			void this.#query.load();
			this.#stop = this.#query.live({ everyMs: 60_000, keys: ['health'] });
		}
		return () => {
			if (--this.#subscribers === 0) {
				this.#stop?.();
				this.#stop = null;
			}
		};
	}

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
