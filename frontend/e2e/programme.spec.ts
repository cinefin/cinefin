import { expect, test } from '@playwright/test';

test('seeded programme detail: rundown, and the bill collapses to a poster rail', async ({
	page
}) => {
	await page.goto('/app/programmes');
	await page
		.getByRole('link', { name: /\[Demo\]/ })
		.first()
		.click();
	await expect(page).toHaveURL(/\/app\/programmes\/\d+/);
	await expect(page.getByText(/Feature|Media|Trailer/i).first()).toBeVisible();

	// Two columns exist from lg; the default 1280 viewport is past that.
	const bill = page.locator('aside');
	const railButton = bill.getByRole('button', { name: 'Show the bill' });
	await expect(bill.locator('section').first()).toBeVisible();
	await page.getByRole('button', { name: 'Hide the bill' }).click();
	await expect(bill.locator('section').first()).toBeHidden();
	await expect(railButton.locator('img, span[title]')).not.toHaveCount(0);
	await railButton.click();
	await expect(bill.locator('section').first()).toBeVisible();
});

test('new programme: start from a template, its slot filled from the strip', async ({ page }) => {
	await page.goto('/app/programmes/new');
	await expect(page.getByText(/Pick a template above, or Blank/)).toBeVisible();

	await page.getByRole('button', { name: 'Add movies' }).click();
	const picker = page.locator('dialog[open]');
	await picker.getByRole('button', { name: 'Add', exact: true }).first().click();
	await expect(picker.getByRole('button', { name: 'Added', exact: true }).first()).toBeVisible();
	await page.keyboard.press('Escape');
	await expect(picker).toBeHidden();

	// Every template is offered; one that takes a different count says so.
	await expect(page.getByRole('button', { name: /Double Bill/ })).toContainText('you have 1');
	await page.getByRole('button', { name: /Single Feature/ }).click();

	await expect(page.getByRole('heading', { name: 'Running order' })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Change movie' })).toBeVisible();
	await expect(page.getByText(/\d+ items ·/).first()).toBeVisible({ timeout: 15_000 });

	await page.getByRole('button', { name: 'Create programme' }).click();
	await page.waitForURL(/\/app\/programmes\/\d+$/, { timeout: 20_000 });
	await expect(page.getByText(/Feature|Running order|Rundown/i).first()).toBeVisible();
});

test('new programme: Blank hands the chosen movies to the editor', async ({ page }) => {
	await page.goto('/app/programmes/new?movies=1');
	await page.getByRole('button', { name: /^Blank/ }).click();
	await expect(page.locator('[data-block-index="0"]')).toContainText('Feature');
	await expect(page.locator('[data-block-index="1"]')).toHaveCount(0);
	// The editor takes the name the movies suggest.
	await expect(page.getByRole('textbox', { name: 'Name' })).not.toHaveValue('');
});

test('editor: a movie block takes its picked film; a certification block offers the rundown films', async ({
	page
}) => {
	await page.goto('/app/programmes/new');
	await page.getByRole('button', { name: /^Blank/ }).click();

	const addMovie = async (row: number) => {
		await page.getByRole('button', { name: 'Movie', exact: true }).first().click();
		const picker = page.locator('dialog[open]');
		await picker.locator('ul > li button').nth(row).click();
		await expect(picker).toBeHidden();
	};

	// Regression: the film picked as the block was added used to land on an unrendered object.
	await addMovie(0);
	await expect(
		page.locator('[data-block-index="0"]').getByRole('button', { name: 'Change movie' })
	).toBeVisible();

	await page.getByRole('button', { name: 'Certification', exact: true }).first().click();
	const options = page.locator('[data-block-index="1"] select option');
	// The placeholder plus exactly the rundown's one film.
	await expect(options).toHaveCount(2);
	const firstFilm = await options.nth(1).innerText();

	// A second feature appears live, and drops out again when its block leaves.
	await addMovie(1);
	await expect(options).toHaveCount(3);
	await page.locator('[data-block-index="2"] button[title="Remove"]').click();
	await page.getByRole('button', { name: 'Delete', exact: true }).click();
	await expect(options).toHaveCount(2);
	await expect(options.nth(1)).toHaveText(firstFilm);
});
