import { expect, test } from '@playwright/test';

// The Add a player wizard up to its pair call. No player runs in the smoke
// environment, so the call fails: that failure must be shown, not swallowed.
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

	await expect(dialog.getByRole('heading', { name: 'Enter the code on the screen' })).toBeVisible();
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
	// The code is cleared for the next try.
	await expect(box(1)).toHaveValue('');
});
