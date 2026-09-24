import { expect, test } from '@playwright/test';

test('seeded programme detail shows its rundown', async ({ page }) => {
	await page.goto('/app/programmes');
	const row = page.getByRole('link', { name: /\[Demo\]/ }).first();
	await expect(row).toBeVisible();
	await row.click();
	await expect(page).toHaveURL(/\/app\/programmes\/\d+/);
	// The rundown/running order renders with typed blocks.
	await expect(page.getByText(/Feature|Media|Trailer/i).first()).toBeVisible();
});

test('create a programme with the films-first wizard', async ({ page }) => {
	await page.goto('/app/programmes/create');

	// Step 1 with nothing brought from the library: the films are the subject,
	// so the page asks for them before a template is mentioned.
	await expect(page.getByText('No movies chosen yet')).toBeVisible();
	await expect(page.getByRole('button', { name: /Choose a template/ })).toBeDisabled();

	// Add one film from the multi picker (Add per row, close when done).
	await page.getByRole('button', { name: 'Add movies' }).first().click();
	const picker = page.locator('dialog[open]');
	await expect(picker).toBeVisible();
	await picker.getByRole('button', { name: 'Add', exact: true }).first().click();
	await expect(picker.getByRole('button', { name: 'Added', exact: true }).first()).toBeVisible();
	await page.keyboard.press('Escape');
	await expect(picker).toBeHidden();

	// The movie is a card of its own — visible before any template exists.
	// (The card carries its position as "01" and its type as a badge.)
	await expect(page.getByText('Feature', { exact: true })).toBeVisible();

	// Step 2 offers only templates that take exactly one feature; the seeded
	// two-feature template is shown on request, and ruled out.
	await page.getByRole('button', { name: /Choose a template/ }).click();
	await expect(page.getByText(/exactly 1 movie/)).toBeVisible();
	await page.getByRole('button', { name: /Show the other/ }).click();
	await expect(page.getByRole('button', { name: /Double Bill/ })).toBeDisabled();

	const templateCard = page.getByRole('button', { name: /Single Feature/ });
	await expect(templateCard).toBeEnabled();
	await templateCard.click();

	// Step 3: the template's real structure with the film in its slot.
	await expect(page.getByRole('heading', { name: 'Running order' })).toBeVisible();
	await expect(page.getByText('1 feature slot')).toBeVisible();
	await expect(page.getByText(/Trailers/).first()).toBeVisible();

	// The track choice made on the films step reads as one line here, and the
	// Tracks… dialog is offered (disabled for demo films, which carry no
	// track data).
	const slot = page.locator('ol > li').filter({ hasText: 'Feature' }).last();
	await expect(slot.getByText('Default audio · no subtitles')).toBeVisible();
	await expect(slot.getByRole('button', { name: 'Tracks…' })).toBeDisabled();

	// Every feature in place → the live preview turns the footer into real
	// numbers.
	await expect(page.getByText(/\d+ items ·/).first()).toBeVisible({ timeout: 15_000 });

	// Create → the "what next?" dialog → View lands on the new programme's
	// detail with its generated rundown.
	await page.getByRole('button', { name: 'Create programme' }).click();
	await page.getByRole('button', { name: 'View programme' }).click({ timeout: 20_000 });
	await page.waitForURL(/\/app\/programmes\/\d+/);
	await expect(page.getByText(/Feature|Running order|Rundown/i).first()).toBeVisible();
});

test('the wizard goes back and re-asks for a template when the films change', async ({ page }) => {
	await page.goto('/app/programmes/create');
	await page.getByRole('button', { name: 'Add movies' }).first().click();
	const picker = page.locator('dialog[open]');
	await picker.getByRole('button', { name: 'Add', exact: true }).first().click();
	await page.keyboard.press('Escape');
	await page.getByRole('button', { name: /Choose a template/ }).click();
	await page.getByRole('button', { name: /Single Feature/ }).click();
	await expect(page.getByRole('heading', { name: 'Running order' })).toBeVisible();

	// The stepper goes back any number of steps: step 1 from step 3.
	await page.locator('ol > li button').first().click();
	await expect(page.getByRole('heading', { name: 'The movies' })).toBeVisible();

	// Adding a feature invalidates the one-feature template, and says so.
	await page.getByRole('button', { name: /Add a random movie/ }).click();
	await page.getByRole('button', { name: /Use pick/ }).click();
	await expect(page.getByText(/doesn't take 2 movies/)).toBeVisible();
	await page.getByRole('button', { name: /Choose a template/ }).click();
	await expect(page.getByRole('button', { name: /Single Feature/ })).toHaveCount(0);
	await expect(page.getByRole('button', { name: /Double Bill/ })).toBeEnabled();
});

test('a movie block takes the film picked when it was added', async ({ page }) => {
	// Regression: the editor store handed `add()` callers the raw object it
	// had just pushed rather than the $state proxy the array stores, so the
	// film chosen in the picker that opens with a new Movie block landed in
	// an object nothing was rendering — the block stayed empty until you
	// picked a second time.
	await page.goto('/app/programmes/new');
	await page.getByRole('button', { name: 'Movie', exact: true }).first().click();

	const picker = page.locator('dialog[open]');
	await expect(picker).toBeVisible();
	await picker.locator('ul > li button').first().click();
	await expect(picker).toBeHidden();

	const block = page.locator('[data-block-index="0"]');
	await expect(block.getByText('No movie chosen yet.')).toHaveCount(0);
	await expect(block.getByRole('button', { name: 'Change movie' })).toBeVisible();
});

test('a certification block offers only the films in the programme, live', async ({ page }) => {
	// A rating card introduces a feature this programme is about to show, so
	// the select must offer the rundown's own films — it used to offer a
	// capped first page of the whole library instead.
	await page.goto('/app/programmes/new');

	const addMovie = async (row: number) => {
		await page.getByRole('button', { name: 'Movie', exact: true }).first().click();
		const picker = page.locator('dialog[open]');
		await expect(picker).toBeVisible();
		await picker.locator('ul > li button').nth(row).click();
		await expect(picker).toBeHidden();
	};

	await addMovie(0);
	await page.getByRole('button', { name: 'Certification', exact: true }).first().click();

	// New blocks open on add, so the config select is on screen already.
	const cert = page.locator('[data-block-index="1"]');
	const options = cert.locator('select option');
	// One film in the rundown → the placeholder plus exactly that film.
	await expect(options).toHaveCount(2);
	const firstFilm = await options.nth(1).innerText();

	// A second feature appears in the select without reopening anything.
	await addMovie(1);
	await expect(options).toHaveCount(3);
	const bothFilms = await options.allInnerTexts();
	expect(bothFilms.slice(1)).toContain(firstFilm);
	expect(new Set(bothFilms.slice(1)).size).toBe(2);

	// And drops out again when its block leaves the rundown.
	await page.locator('[data-block-index="2"] button[title="Remove"]').click();
	await page.getByRole('button', { name: 'Delete', exact: true }).click();
	await expect(options).toHaveCount(2);
	await expect(options.nth(1)).toHaveText(firstFilm);
});
