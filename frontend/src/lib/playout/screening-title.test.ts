// node --test (npm run test:unit)
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { screeningTitle } from './screening-title.ts';

const coral = { title: 'Coral Skies' };
const orbit = { title: 'A Quiet Orbit' };

test('a programme named after its one film is just the film', () => {
	for (const name of [
		'Coral Skies',
		'coral skies',
		'Coral Skies (2021)',
		'Coral Skies 2021',
		'Coral Skies!'
	])
		assert.deepEqual(screeningTitle(name, [coral]), {
			title: 'Coral Skies',
			film: coral,
			films: []
		});
});

test('a programme with its own name lists its films under it', () => {
	assert.deepEqual(screeningTitle('Sunday Family Matinee', [orbit]), {
		title: 'Sunday Family Matinee',
		film: null,
		films: [orbit]
	});
	assert.deepEqual(screeningTitle('Coral Skies', [coral, orbit]).films, [coral, orbit]);
});

test('a programme without films keeps its name', () => {
	assert.deepEqual(screeningTitle('Quiz night', []), {
		title: 'Quiz night',
		film: null,
		films: []
	});
});
