import { defineConfig } from '@playwright/test';

// The smoke pack: the load-bearing flows against a seeded throwaway Django server
// (scripts/e2e-server.sh). The SPA is built first so Django serves the production artifact.
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
