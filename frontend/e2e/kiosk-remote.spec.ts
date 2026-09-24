import { expect, test } from '@playwright/test';

test('kiosk renders a layout with seeded films', async ({ page }) => {
	// The poster wall is images-only (titles are art, not text), so posters
	// ARE the assertion; the board layout then proves text content renders.
	await page.goto('/app/kiosk?layout=wall&takeover=0&night=0');
	await expect(page.locator('img[alt=""]').first()).toBeVisible({ timeout: 15_000 });

	await page.goto('/app/kiosk?layout=board&takeover=0&night=0');
	await expect(page.getByText(/\[Demo\]/).first()).toBeVisible({ timeout: 15_000 });
});

test('remote renders the agent-down state honestly', async ({ page }) => {
	await page.goto('/app/remote');
	// No playout host is configured in the smoke environment — the console
	// must say so rather than pretend or wedge.
	await expect(page.getByText(/not connected/i).first()).toBeVisible();
});
