import { expect, test } from '@playwright/test';

test('kiosk shows each between-screenings option', async ({ page }) => {
	for (const between of ['whats_on', 'screenings', 'films', 'week']) {
		await page.goto(`/app/kiosk?between=${between}`);
		await expect(page.getByText(/\[Demo\]/).first()).toBeVisible({ timeout: 15_000 });
	}
});

test('kiosk poster mode shows a full-screen poster', async ({ page }) => {
	await page.goto('/app/kiosk?mode=posters');
	await expect(page.locator('.kiosk img').first()).toBeVisible({ timeout: 15_000 });
});

test('remote renders the agent-down state honestly', async ({ page }) => {
	await page.goto('/app/remote');
	// No playout host is configured in the smoke environment — the console
	// must say so rather than pretend or wedge.
	await expect(page.getByText(/No player is set up|is offline/).first()).toBeVisible();
});
