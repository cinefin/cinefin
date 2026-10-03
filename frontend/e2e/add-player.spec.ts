import { expect, test } from '@playwright/test';

// No player runs in the smoke environment, so pairing fails: that must be shown, not swallowed.
test('add a player: name, then the code boxes', async ({ page }) => {
	await page.goto('/app/settings?tab=playout');
	await page
		.getByRole('button', { name: /Add a player/ })
		.first()
		.click();

	const dialog = page.getByRole('dialog');
	await expect(dialog.getByRole('heading', { name: 'Find the player' })).toBeVisible();
	const next = dialog.getByRole('button', { name: /Next/ });
	await expect(next).toBeDisabled();

	// An address offers its host name as the player's name.
	await dialog.getByLabel(/add it by address/).fill('127.0.0.1:9');
	await expect(dialog.getByLabel('Player name')).toHaveValue('127.0.0.1');
	await dialog.getByLabel('Player name').fill('Smoke room');
	await next.click();

	await expect(dialog.getByRole('heading', { name: 'Pair Smoke room' })).toBeVisible();
	await expect(dialog.getByText('Smoke room shows a six-digit code')).toBeVisible();

	// Typing moves box to box; Backspace steps back.
	const box = (n: number) => dialog.getByLabel(`Digit ${n}`);
	await box(1).focus();
	await page.keyboard.type('12');
	await expect(box(2)).toHaveValue('2');
	await expect(box(3)).toBeFocused();
	await page.keyboard.press('Backspace');
	await expect(box(2)).toHaveValue('');
	await expect(box(2)).toBeFocused();

	// A pasted code fills every box, and a full code pairs at once.
	await box(2).evaluate((el) => {
		const data = new DataTransfer();
		data.setData('text', '482 913');
		el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: data, bubbles: true }));
	});
	await expect(dialog.getByRole('alert')).toContainText(/No player answered/);
	await expect(box(1)).toHaveValue('');
});

// A plain mpv the operator runs: no pairing, just its socket, then Finish.
test('add a player: a local mpv socket instead of the agent', async ({ page }) => {
	await page.goto('/app/settings?tab=playout');
	await page
		.getByRole('button', { name: /Add a player/ })
		.first()
		.click();

	const dialog = page.getByRole('dialog');
	await dialog.getByRole('button', { name: 'Use a local mpv socket' }).click();
	await expect(dialog.getByRole('heading', { name: 'Add a local mpv' })).toBeVisible();
	const add = dialog.getByRole('button', { name: 'Add', exact: true });
	await expect(add).toBeDisabled();

	await dialog.getByLabel('Socket path').fill('/tmp/smoke-mpv.sock');
	await dialog.getByLabel('Player name').fill('Smoke mpv');
	await expect(dialog.getByText('--input-ipc-server=/tmp/smoke-mpv.sock')).toBeVisible();
	await add.click();

	await expect(dialog.getByRole('heading', { name: 'Finish' })).toBeVisible();
	// The step list names Finish too; the button row's is the last.
	await dialog.getByRole('button', { name: 'Finish' }).last().click();
	await expect(page.getByRole('button', { name: /Smoke mpv/ }).first()).toBeVisible();
});
