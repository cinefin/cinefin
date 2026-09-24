import { expect, test } from '@playwright/test';

test('root redirects to the SPA and the shell renders', async ({ page }) => {
	await page.goto('/');
	await expect(page).toHaveURL(/\/app\/?$/);

	// The sidebar carries every live section. Scoped to the nav landmark: page
	// content links to these sections too (a dashboard panel heading to the
	// library, say), and this assertion is about the sidebar.
	const nav = page.getByRole('navigation', { name: 'Main' });
	for (const label of ['Dashboard', 'Remote', 'Library', 'Programmes', 'Schedules', 'Settings']) {
		await expect(nav.getByRole('link', { name: label, exact: true })).toBeVisible();
	}

	// Dashboard content arrives (seeded library stats), and the booth lamp
	// settles on a real state rather than "Connecting".
	await expect(page.getByText(/On air|Paused|Cued|Idle|Status unavailable/).first()).toBeVisible();
});
