import { test } from 'node:test';
import assert from 'node:assert/strict';
import { demoDatabaseUrl, isDemoMutation } from '../src/lib/server/demo-policy.ts';

test('demo rejects a production URL even when demo mode is enabled', () => {
	assert.throws(() => demoDatabaseUrl('postgresql://owner:pass@host/production'));
	assert.throws(() => demoDatabaseUrl('postgresql://owner:pass@host/lfm_demo'));
	assert.equal(demoDatabaseUrl('postgresql://lfm_demo:lfm_demo@database/lfm_demo'),
		'postgresql://lfm_demo:lfm_demo@database/lfm_demo');
});

test('all mutations are blocked, including SvelteKit form actions', () => {
	for (const method of ['POST', 'PATCH', 'PUT', 'DELETE']) assert.equal(isDemoMutation(method), true);
	for (const method of ['GET', 'HEAD', 'OPTIONS']) assert.equal(isDemoMutation(method), false);
});
