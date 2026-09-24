import { expect, test } from '@playwright/test';

test('trailers page mounts with its toolbar and stats', async ({ page }) => {
	// Regression guard: a use-before-declaration once crashed this page on
	// mount, leaving nothing rendered — so the assertion is that it renders.
	const errors: string[] = [];
	page.on('pageerror', (e) => errors.push(String(e)));
	await page.goto('/app/trailers');
	await expect(page.getByRole('heading', { name: /Trailer library/i }).first()).toBeVisible();
	await expect(page.getByPlaceholder(/Search/i).first()).toBeVisible();
	expect(errors).toEqual([]);
});
