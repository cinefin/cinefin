import { expect, test } from '@playwright/test';

test('ticket designer: add a columns row, edit a cell item, undo, and it saves', async ({
	page
}) => {
	await page.goto('/app/settings?tab=tickets');
	const strip = page.locator('.strip');
	// The ticket previews as one image the server draws, with a region over each line.
	await expect(strip.locator('img')).toHaveAttribute('src', /^data:image\/png/);
	const lines = page.getByText(/^Line \d+ of (\d+)$/);
	const total = async () => Number((await lines.innerText()).match(/of (\d+)/)![1]);
	const before = await total();

	await page.getByRole('button', { name: 'Add a line' }).click();
	await page.getByRole('menuitem', { name: 'Columns' }).click();
	await expect.poll(total).toBe(before + 1);
	const row = before + 1; // added after the selected first line: line 2

	await page.getByRole('button', { name: 'Line 2, cell 2, item 2' }).click();
	const text = page.getByLabel('Text', { exact: true });
	await expect(text).toHaveValue('Seat {seat}');
	await text.fill('Row {seat}');

	// Undo (the button; the keyboard shortcut skips text fields) takes the whole edit back.
	await page.getByRole('button', { name: 'Undo', exact: true }).click();
	await expect(text).toHaveValue('Seat {seat}');
	await page.getByRole('button', { name: 'Undo', exact: true }).click();
	await expect.poll(total).toBe(before);

	await page.getByRole('button', { name: 'Redo', exact: true }).click();
	await expect.poll(total).toBe(row);
	// Saves are debounced; give the last one time to land before reloading.
	await page.waitForTimeout(1200);
	await page.reload();
	await expect(page.getByRole('button', { name: 'Line 2, cell 1', exact: true })).toBeVisible();
});

test('ticket designer: a new design can start from a starter', async ({ page }) => {
	await page.goto('/app/settings?tab=tickets');
	await expect(page.locator('.strip img')).toBeVisible();
	// The menu, not a design already called "New design".
	await page.locator('[data-menu-trigger]').filter({ hasText: 'New design' }).click();
	await page.getByRole('menuitem', { name: 'Compact' }).click();
	// Compact puts a QR code beside the details, in columns.
	await expect(page.getByRole('button', { name: 'Line 3, cell 1', exact: true })).toBeVisible();
});
