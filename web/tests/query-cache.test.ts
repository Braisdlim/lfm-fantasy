import { test } from 'node:test';
import assert from 'node:assert/strict';
import { QueryCache } from '../src/lib/server/query-cache.ts';

test('parallel identical reads perform one database request', async () => {
	const cache = new QueryCache();
	let calls = 0;
	const load = async () => { calls++; return [42]; };
	const values = await Promise.all(Array.from({ length: 20 }, () => cache.read('a', load)));
	assert.equal(calls, 1);
	assert.ok(values.every((x) => x[0] === 42));
});

test('failed reads can retry', async () => {
	const cache = new QueryCache();
	await assert.rejects(cache.read('a', async () => { throw new Error('network'); }));
	assert.deepEqual(await cache.read('a', async () => [2]), [2]);
});

test('invalidation prevents an older response overwriting fresh data', async () => {
	const cache = new QueryCache();
	let finish!: (v: number[]) => void;
	const old = cache.read('a', () => new Promise<number[]>((resolve) => { finish = resolve; }));
	await Promise.resolve();
	cache.clear();
	assert.deepEqual(await cache.read('a', async () => [2]), [2]);
	finish([1]);
	await old;
	assert.deepEqual(await cache.read('a', async () => [3]), [2]);
});

test('expired data is reloaded', async () => {
	const cache = new QueryCache();
	await cache.read('a', async () => [1], -1);
	assert.deepEqual(await cache.read('a', async () => [2]), [2]);
});
