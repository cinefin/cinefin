import { expect, test } from '@playwright/test';

test('library: search narrows, the film drawer opens, swaps and closes, Sync goes to Settings', async ({
	page
}) => {
	await page.goto('/app/library');

	// Seeded titles carry the "[Demo] " prefix.
	const demoCards = page.getByText(/\[Demo\]/);
	await expect(demoCards.first()).toBeVisible();

	const search = page.getByPlaceholder(/Search movies/);
	await search.fill('zzzz-no-such-film');
	await expect(page.getByText(/\[Demo\]/)).toHaveCount(0);
	await search.fill('');

	// The drawer is addressed by ?movie=<id> so Back closes it.
	const title = (await demoCards.first().textContent())?.trim() ?? '';
	await demoCards.first().click();
	await expect(page).toHaveURL(/\/app\/library\?(.*&)?movie=\d+/);
	const drawer = page.getByRole('complementary', { name: title });
	await expect(drawer.getByRole('heading', { name: title })).toBeVisible();
	await expect(drawer.getByRole('heading', { name: 'Certificates' })).toBeVisible();

	// Docked, the grid stays usable: another film swaps the drawer in place.
	const second = (await demoCards.nth(1).textContent())?.trim() ?? '';
	await demoCards.nth(1).click();
	await expect(page.getByRole('complementary', { name: second })).toBeVisible();

	await page.keyboard.press('Escape');
	await expect(page.getByRole('complementary', { name: second })).toBeHidden();
	await expect(page).toHaveURL(/\/app\/library$/);

	// The demo source is disabled, so the header links to Settings instead of syncing in place.
	await page.getByRole('link', { name: 'Sync', exact: true }).click();
	await expect(page).toHaveURL(/\/app\/settings\?tab=library/);
	await expect(
		page
			.getByRole('navigation', { name: 'Settings sections' })
			.getByRole('link', { name: 'Library' })
	).toHaveAttribute('aria-current', 'page');

	// The old sync path still lands there (bookmarks keep working).
	await page.goto('/app/sync');
	await expect(page).toHaveURL(/\/app\/settings\?tab=library/);
});
