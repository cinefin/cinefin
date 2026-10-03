import { expect, test } from '@playwright/test';

test('a setting saves itself, and Undo puts it back', async ({ page }) => {
	await page.goto('/app/settings?tab=cinema');

	// Each setting is a row that says what it is set to; its field opens in place.
	const row = page.getByRole('button', { name: /^Name/ });
	await row.click();
	const name = page.getByLabel(/Theater name/i);
	await expect(name).toBeVisible();
	const newName = `Smoke Theater ${Date.now() % 100000}`;
	await name.fill(newName);

	// No Save button: the change saves a moment later and the header says so.
	await expect(page.getByRole('button', { name: /Save changes/ })).toHaveCount(0);
	await expect(page.getByText(/^Saved \d/).first()).toBeVisible();

	await page.reload();
	await expect(row).toContainText(newName);
	// The topbar brand follows the setting.
	await expect(page.getByRole('link', { name: newName })).toBeVisible();

	await row.click();
	await page.getByLabel(/Theater name/i).fill(`${newName} again`);
	await expect(page.getByText(/^Saved \d/).first()).toBeVisible();
	await page.getByRole('button', { name: 'Undo' }).click();
	await expect(page.getByLabel(/Theater name/i)).toHaveValue(newName);
	await expect(page.getByRole('button', { name: 'Undo' })).toHaveCount(0);
	await page.waitForTimeout(1500);
	await page.reload();
	await expect(row).toContainText(newName);
	await expect(row).not.toContainText('again');
});

test('settings sections are a toolbar, in the agreed order', async ({ page }) => {
	await page.goto('/app/settings');
	const bar = page.getByRole('navigation', { name: 'Settings sections' });
	await expect(bar.getByRole('link')).toHaveText([
		'Playout',
		'Library',
		'Theater',
		'Tickets',
		'Plugins',
		'Kiosk',
		'Appearance',
		'Security',
		'Backup'
	]);
	await expect(bar.getByRole('link', { name: 'Playout' })).toHaveAttribute('aria-current', 'page');
	// Playout always offers to add a player.
	await expect(page.getByRole('button', { name: /Add a player/ })).toBeVisible();

	await bar.getByRole('link', { name: 'Kiosk' }).click();
	await expect(page).toHaveURL(/tab=kiosk/);
	await expect(bar.getByRole('link', { name: 'Kiosk' })).toHaveAttribute('aria-current', 'page');
	// No tabs inside a section: its parts are stacked on the page.
	await expect(page.getByRole('tablist')).toHaveCount(0);
	await expect(page.getByRole('button', { name: /^Night hours/ })).toBeVisible();
});
