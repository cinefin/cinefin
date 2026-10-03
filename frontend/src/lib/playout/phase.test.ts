// node --test (npm run test:unit): the phase helper every playout surface reads.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
	barLines,
	can,
	cuedBy,
	lamp,
	preview,
	primaryAction,
	started,
	type Phase,
	type PlayoutStatus
} from './phase.ts';

const player = {
	id: 1,
	name: 'Living room',
	kind: 'agent',
	show_status: true
};
const programme = {
	id: 7,
	name: 'Friday Night',
	description: '',
	runtime_minutes: 130,
	runtime_formatted: '2h 10m',
	block_count: 4
};
const playback = { position: 6, duration: 15, remaining: 9, percentage: 40 };

function status(phase: Phase, extra: Partial<PlayoutStatus> = {}): PlayoutStatus {
	return { phase, screen: '', label: '', actions: [], player, ...extra };
}

test('the lamp: standby grey, cued green, paused and offline amber, on air the tally', () => {
	assert.deepEqual(lamp(status('standby')), {
		label: 'Standby',
		colour: 'neutral',
		quiet: true
	});
	assert.equal(lamp(status('cued')).colour, 'green');
	assert.equal(lamp(status('paused')).colour, 'amber');
	assert.equal(lamp(status('offline')).colour, 'amber');
	for (const phase of ['preshow', 'playing', 'hold'] as const) {
		assert.deepEqual(lamp(status(phase)), { label: 'On air', colour: 'red', tally: true });
	}
	assert.equal(lamp(status('manual')).label, 'On air · manual');
	assert.equal(lamp(null, false).label, 'Connecting…');
	assert.equal(lamp(null).label, 'Status unavailable');
});

test('buttons follow the server actions', () => {
	const cued = status('cued', { actions: ['start', 'cue', 'end'] });
	assert.equal(can(cued, 'start'), true);
	assert.equal(can(cued, 'pause'), false);
	assert.deepEqual(primaryAction(cued), { action: 'start', label: 'Start', enabled: true });

	const paused = status('paused', { actions: ['resume', 'previous', 'next', 'seek', 'end'] });
	assert.equal(primaryAction(paused).action, 'resume');

	const hold = status('hold', { actions: ['previous', 'end_hold', 'end'] });
	assert.deepEqual(primaryAction(hold), { action: 'pause', label: 'Pause', enabled: false });
	assert.equal(can(null, 'cue'), false);
});

test('started covers the pre-show, items, a pause and a hold, only with a programme', () => {
	assert.equal(started(status('preshow', { programme })), true);
	assert.equal(started(status('paused', { programme })), true);
	assert.equal(started(status('cued', { programme })), false);
	assert.equal(started(status('paused')), false); // a paused manual queue
});

test('bar lines per phase', () => {
	assert.deepEqual(barLines(status('offline'), 'http://10.0.0.5:8089'), {
		title: 'Living room',
		type: null,
		detail: "Can't reach the player at http://10.0.0.5:8089"
	});
	assert.equal(barLines(status('offline')).detail, "Can't reach the player");
	assert.equal(
		barLines(status('standby', { screen: 'System Ident' })).detail,
		'On screen · System Ident, held'
	);
	const next_item = { type: 'certification', position: 0, title: 'BBFC 15', details: {} };
	assert.deepEqual(barLines(status('cued', { programme, screen: 'Standby', next_item })), {
		title: 'Friday Night',
		type: null,
		detail: 'On screen · Standby · First up: BBFC 15'
	});
	assert.equal(
		barLines(status('preshow', { programme, playback })).detail,
		'Pre-show · Title card · 0:09 left'
	);
	const current_item = { type: 'movie', position: 6, title: 'Alien', details: {} };
	const playlist = {
		total_items: 9,
		offset: 1,
		programme_total_duration: 1,
		programme_elapsed_time: 0,
		programme_remaining_time: 1
	};
	assert.deepEqual(barLines(status('playing', { programme, current_item, playlist })), {
		title: 'Friday Night',
		type: 'movie',
		detail: '7 of 9 · Alien'
	});
	const command = { type: 'command', position: 2, title: 'Dim the lights', details: {} };
	// The command type's short label, "Hold", leads the line.
	assert.deepEqual(barLines(status('hold', { programme, current_item: command, playback })), {
		title: 'Friday Night',
		type: 'command',
		detail: 'Dim the lights · 0:09 left'
	});
});

test('a cued programme starts at its screening once the lead-in has begun', () => {
	const soon = {
		id: 1,
		programme_id: 7,
		programme_name: 'Friday Night',
		start_time: '2026-10-02T20:00:00Z',
		cue_time: '2026-10-02T19:55:00Z'
	};
	const cued = status('cued', { programme, screen: 'Title card', next_screening: soon });
	assert.equal(cuedBy(cued, Date.parse('2026-10-02T19:56:00Z')), soon);
	assert.equal(cuedBy(cued, Date.parse('2026-10-01T12:00:00Z')), null); // cued by hand, a day early
});

test('the on-screen preview', () => {
	assert.equal(preview(status('standby', { screen: 'System Ident' })).kind, 'mark');
	assert.equal(preview(status('cued', { screen: 'Standby' })).kind, 'mark');
	assert.deepEqual(preview(status('cued', { screen: 'Title card', programme })), {
		kind: 'title',
		text: 'Friday Night'
	});
	assert.deepEqual(preview(status('playing', { screen: 'Alien' })), {
		kind: 'item',
		text: 'Alien'
	});
	assert.equal(preview(status('hold')).kind, 'black');
});
