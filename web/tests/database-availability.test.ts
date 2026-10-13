import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseAvailability, DatabaseQuotaError, isDatabaseQuotaError } from '../src/lib/server/database-availability.ts';

test('recognizes the actual Neon HTTP 402 error and the Postgres compute quota error', () => {
	for (const message of [
		'Server error (HTTP status 402): {"message":"Your account or project has exceeded the quota. Upgrade your plan to increase limits."}',
		'ERROR: Your account or project has exceeded the compute time quota.'
	]) assert.equal(isDatabaseQuotaError(new Error(message)), true);
	assert.equal(isDatabaseQuotaError(new Error('column "quota" does not exist')), false);
	assert.equal(isDatabaseQuotaError(new Error('fetch failed')), false);
});

test('stops database requests during a quota suspension and recovers after the cooldown', async () => {
	let now = 10_000;
	let calls = 0;
	const availability = new DatabaseAvailability(() => now);
	await assert.rejects(availability.run(async () => {
		calls++;
		throw new Error('Your account or project has exceeded the quota.');
	}), DatabaseQuotaError);
	for (let i = 0; i < 20; i++) {
		await assert.rejects(availability.run(async () => { calls++; return [1]; }), DatabaseQuotaError);
	}
	assert.equal(calls, 1);
	now += 60_000;
	assert.deepEqual(await availability.run(async () => { calls++; return [2]; }), [2]);
	assert.equal(calls, 2);
});

test('other errors retain their identity and can retry immediately', async () => {
	const availability = new DatabaseAvailability();
	const failure = new Error('fetch failed');
	await assert.rejects(availability.run(async () => { throw failure; }), (e) => e === failure);
	assert.equal(await availability.run(async () => 42), 42);
});
