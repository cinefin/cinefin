import { defineConfig } from '@playwright/test';

/**
 * The smoke pack: five end-to-end flows against a real, seeded Django server
 * (scripts/e2e-server.sh — throwaway DB, seed_demo data, auth off). Run with
 * `npm run e2e`; the config builds the SPA first so Django serves the same
 * artifact production would.
 *
 * This is deliberately a SMOKE pack, not a test suite: it proves the app
 * boots, the five load-bearing flows work, and the SPA↔API contract holds.
 * Correctness lives in pytest and svelte-check.
 */
export default defineConfig({
	testDir: './e2e',
	fullyParallel: false, // one shared server + seeded DB; keep flows serial
	workers: 1,
	retries: 1, // one retry absorbs dev-server warmup flakes, not real bugs
	timeout: 30_000,
	use: {
		baseURL: 'http://127.0.0.1:8799',
		trace: 'retain-on-failure',
		// PLAYWRIGHT_CHROMIUM_PATH: run against a system chromium instead of the
		// downloaded browser (for boxes where `npx playwright install` can't).
		...(process.env.PLAYWRIGHT_CHROMIUM_PATH
			? { launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH } }
			: {})
	},
	webServer: {
		command: 'npm run build && E2E_PORT=8799 bash ../scripts/e2e-server.sh',
		url: 'http://127.0.0.1:8799/api/v2/health',
		reuseExistingServer: false,
		stdout: 'ignore',
		timeout: 180_000
	}
});
