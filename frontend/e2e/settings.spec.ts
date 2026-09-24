import { expect, test } from '@playwright/test';

test('settings save persists across reload', async ({ page }) => {
	await page.goto('/app/settings?tab=cinema');

	const name = page.getByLabel(/Theater name/i);
	await expect(name).toBeVisible();
	const newName = `Smoke Theater ${Date.now() % 100000}`;
	await name.fill(newName);

	await page.getByRole('button', { name: /Save changes/ }).click();
	// The dirty indicator clears once the save round-trips.
	await expect(page.getByRole('button', { name: /Saving/ })).toHaveCount(0);

	await page.reload();
	await expect(page.getByLabel(/Theater name/i)).toHaveValue(newName);
	// The topbar brand follows the setting.
	await expect(page.getByRole('heading', { name: newName })).toBeVisible();
});
