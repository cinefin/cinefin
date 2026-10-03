import { expect, test } from '@playwright/test';

test('root redirects to the SPA, the shell renders and the trailers page mounts', async ({
	page
}) => {
	await page.goto('/');
	await expect(page).toHaveURL(/\/app\/?$/);

	// Scoped to the sidebar: page content links to these sections too.
	const nav = page.getByRole('navigation', { name: 'Main' });
	for (const label of ['Dashboard', 'Remote', 'Library', 'Programmes', 'Schedules', 'Settings']) {
		await expect(nav.getByRole('link', { name: label, exact: true })).toBeVisible();
	}
	// The booth lamp settles on a real state rather than "Connecting".
	await expect(
		page.getByText(/On air|Paused|Cued|Standby|Offline|Status unavailable/).first()
	).toBeVisible();

	// A use-before-declaration once crashed this page on mount, leaving nothing rendered.
	const errors: string[] = [];
	page.on('pageerror', (e) => errors.push(String(e)));
	await nav.getByRole('link', { name: 'Trailers', exact: true }).click();
	await expect(page.getByPlaceholder(/Search/i).first()).toBeVisible();
	expect(errors).toEqual([]);
});
