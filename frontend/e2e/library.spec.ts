import { expect, test } from '@playwright/test';

test('library lists seeded films, search narrows, film drawer opens and closes', async ({
	page
}) => {
	await page.goto('/app/library');

	// Seeded titles carry the "[Demo] " prefix.
	const demoCards = page.getByText(/\[Demo\]/);
	await expect(demoCards.first()).toBeVisible();

	// Search narrows the grid (a term no demo title contains empties it).
	const search = page.getByPlaceholder(/Search movies/);
	await search.fill('zzzz-no-such-film');
	await expect(page.getByText(/\[Demo\]/)).toHaveCount(0);
	await search.fill('');

	// Open the first film: the drawer carries the full film view and the URL
	// addresses it (?movie=<id>) so Back closes it and stays on the library.
	const title = (await demoCards.first().textContent())?.trim() ?? '';
	await demoCards.first().click();
	await expect(page).toHaveURL(/\/app\/library\?(.*&)?movie=\d+/);
	const drawer = page.getByRole('complementary', { name: title });
	await expect(drawer).toBeVisible();
	await expect(drawer.getByRole('heading', { name: title })).toBeVisible();
	await expect(drawer.getByRole('heading', { name: 'Certificates' })).toBeVisible();
	await expect(drawer.getByRole('button', { name: 'Select', exact: true })).toBeVisible();

	// Docked (wide screen): the grid stays usable — another film swaps the drawer in place.
	const second = (await demoCards.nth(1).textContent())?.trim() ?? '';
	await demoCards.nth(1).click();
	await expect(page.getByRole('complementary', { name: second })).toBeVisible();

	// Escape closes the drawer and the URL returns to the plain library.
	await page.keyboard.press('Escape');
	await expect(page.getByRole('complementary', { name: second })).toBeHidden();
	await expect(page).toHaveURL(/\/app\/library$/);
});

test.describe('on a phone', () => {
	test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

	test('the film drawer covers the screen and Back closes it', async ({ page }) => {
		await page.goto('/app/library');
		const demoCards = page.getByText(/\[Demo\]/);
		const title = (await demoCards.first().textContent())?.trim() ?? '';
		await demoCards.first().click();

		const drawer = page.getByRole('dialog', { name: title });
		await expect(drawer).toBeVisible();
		const box = await drawer.boundingBox();
		expect(box?.width).toBeCloseTo(390, 0);
		await expect(drawer.getByRole('link', { name: /Create programme/ })).toBeInViewport();

		await page.goBack();
		await expect(drawer).toBeHidden();
		await expect(page).toHaveURL(/\/app\/library$/);
	});
});

test('the library sends you to the one source in Settings', async ({ page }) => {
	await page.goto('/app/library');
	// The demo source is disabled (it points at a fake host), so the header
	// offers a link to Settings rather than an in-place background sync — an
	// enabled source gets the [Sync ▾] split button instead.
	await page.getByRole('link', { name: 'Sync', exact: true }).click();
	await expect(page).toHaveURL(/\/app\/settings\?tab=library/);
	await expect(page.getByRole('heading', { name: 'Library source' })).toBeVisible();

	// The old sync path still lands somewhere sensible (bookmarks keep working).
	await page.goto('/app/sync');
	await expect(page).toHaveURL(/\/app\/settings\?tab=library/);
});
