import { expect, test } from '@playwright/test';

test('ticket designer: add a columns row, edit a cell item, undo, and it saves', async ({
	page
}) => {
	// Settings › Tickets lists the designs; each opens on its own page.
	await page.goto('/app/settings?tab=tickets');
	await page.getByRole('button', { name: /Standard/ }).click();
	await expect(page).toHaveURL(/\/app\/settings\/tickets\/\d+$/);
	// The ticket previews as one image the server draws, with a region over each line.
	await expect(page.locator('.strip img')).toHaveAttribute('src', /^data:image\/png/);
	const lines = page.getByText(/^Line \d+ of (\d+)$/);
	const total = async () => Number((await lines.innerText()).match(/of (\d+)/)![1]);
	const before = await total();

	await page.getByRole('button', { name: 'Add a line' }).click();
	await page.getByRole('menuitem', { name: 'Columns' }).click();
	await expect.poll(total).toBe(before + 1);

	await page.getByRole('button', { name: 'Line 2, cell 2, item 2' }).click();
	const text = page.getByLabel('Text', { exact: true });
	await expect(text).toHaveValue('Seat {seat}');
	await text.fill('Row {seat}');

	// The Undo button (the shortcut skips text fields) takes the whole edit back.
	const undo = page.getByRole('button', { name: 'Undo', exact: true });
	await undo.click();
	await expect(text).toHaveValue('Seat {seat}');
	await undo.click();
	await expect.poll(total).toBe(before);
	await page.getByRole('button', { name: 'Redo', exact: true }).click();
	await expect.poll(total).toBe(before + 1);

	// Saves are debounced; give the last one time to land before reloading.
	await page.waitForTimeout(1200);
	await page.reload();
	await expect(page.getByRole('button', { name: 'Line 2, cell 1', exact: true })).toBeVisible();
});
