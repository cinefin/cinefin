import { expect, test } from '@playwright/test';

// The two columns (and therefore the collapse) only exist at lg and up; the
// Playwright default viewport is 1280 wide, comfortably past that.

test('the programme bill collapses to a poster rail and comes back', async ({ page }) => {
	await page.goto('/app/programmes');
	await page
		.getByRole('link', { name: /\[Demo\]/ })
		.first()
		.click();
	await page.waitForURL(/\/app\/programmes\/\d+/);

	const bill = page.locator('aside');
	const railButton = bill.getByRole('button', { name: 'Show the bill' });

	// Open: the bill is on screen, the rail is not.
	await expect(bill.getByRole('heading', { level: 1 })).toBeVisible();
	await expect(railButton).toBeHidden();

	// Collapse from the tab strip.
	await page.getByRole('button', { name: 'Hide the bill' }).click();
	await expect(bill.getByRole('heading', { level: 1 })).toBeHidden();
	await expect(railButton).toBeVisible();
	// The rail still says which films: one poster cell per feature.
	await expect(railButton.locator('img, span[title]')).not.toHaveCount(0);

	// The rail itself is the way back.
	await railButton.click();
	await expect(bill.getByRole('heading', { level: 1 })).toBeVisible();
	await expect(railButton).toBeHidden();
});

test('editing the rundown takes the width for you, once', async ({ page }) => {
	await page.goto('/app/programmes');
	await page
		.getByRole('link', { name: /\[Demo\]/ })
		.first()
		.click();
	await page.waitForURL(/\/app\/programmes\/\d+/);
	const url = page.url();

	// Entering edit mode collapses the bill without being asked.
	await page.goto(`${url}?edit=1`);
	const bill = page.locator('aside');
	await expect(bill.getByRole('button', { name: 'Show the bill' })).toBeVisible();

	// Reopening it stands: the auto-collapse does not fight you.
	await page.getByRole('button', { name: 'Show the bill' }).first().click();
	await expect(bill.getByRole('heading', { level: 1 })).toBeVisible();
	await expect(bill.getByRole('button', { name: 'Show the bill' })).toBeHidden();
});

test('the template details collapse to a rail of feature slots', async ({ page }) => {
	await page.goto('/app/templates');
	await page
		.getByRole('link', { name: /Single Feature/ })
		.first()
		.click();
	await page.waitForURL(/\/app\/templates\/\d+/);

	const aside = page.locator('aside');
	const railButton = aside.getByRole('button', { name: 'Show the template details' });

	await expect(aside.getByRole('heading', { level: 1 })).toBeVisible();
	await page.getByRole('button', { name: 'Hide the template details' }).click();
	await expect(aside.getByRole('heading', { level: 1 })).toBeHidden();
	await expect(railButton).toBeVisible();
	// One empty frame per feature slot — a template's slots are what it is.
	await expect(railButton.locator('span[title^="Feature"]')).toHaveCount(1);

	await railButton.click();
	await expect(aside.getByRole('heading', { level: 1 })).toBeVisible();
});
