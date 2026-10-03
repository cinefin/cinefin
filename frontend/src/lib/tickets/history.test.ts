// node --test (npm run test:unit): the ticket designer's undo history.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { History } from './history.ts';

test('undo and redo step through recorded edits', () => {
	const h = new History<{ n: number }>();
	h.reset({ n: 0 });
	h.record({ n: 1 });
	h.record({ n: 2 });
	assert.deepEqual(h.undo({ n: 2 }), { n: 1 });
	assert.deepEqual(h.undo({ n: 1 }), { n: 0 });
	assert.equal(h.undo({ n: 0 }), null);
	assert.deepEqual(h.redo({ n: 0 }), { n: 1 });
	assert.deepEqual(h.redo({ n: 1 }), { n: 2 });
	assert.equal(h.canRedo, false);
});

test('a burst of edits to one field is one step', () => {
	const h = new History<string>();
	h.reset('');
	h.record('a', 'content', 1000);
	h.record('ab', 'content', 1500);
	h.record('abc', 'content', 2000);
	h.record('abc!', 'align', 2100);
	h.record('abcd', 'content', 5000);
	assert.equal(h.undo('abcd'), 'abc!');
	assert.equal(h.undo('abc!'), 'abc');
	assert.equal(h.undo('abc'), '');
});

test('a new edit after undo drops the redo branch', () => {
	const h = new History<number>();
	h.reset(0);
	h.record(1);
	h.undo(1);
	h.record(5);
	assert.equal(h.canRedo, false);
	assert.equal(h.undo(5), 0);
});

test('snapshots are copies, not the live document', () => {
	const doc = { items: [1] };
	const h = new History<typeof doc>();
	h.reset(doc);
	doc.items.push(2);
	h.record(doc);
	doc.items.push(3);
	assert.deepEqual(h.undo(doc), { items: [1] });
});
