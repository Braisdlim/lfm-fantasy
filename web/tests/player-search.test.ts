import test from 'node:test';
import assert from 'node:assert/strict';
import { createPlayerSearch, type SearchState } from '../src/lib/player-search.ts';

const tick = () => new Promise((resolve) => setTimeout(resolve, 5));
const response = (name: string) => new Response(JSON.stringify({ results: [name] }));

test('search waits for two letters, coalesces typing and sends the position', async () => {
	const calls: string[] = [];
	let state: SearchState<string> | undefined;
	const search = createPlayerSearch<string>((next) => { state = next; }, {
		delay: 0, fetch: async (url) => { calls.push(String(url)); return response('Lamine'); }
	});
	search.update(' l ');
	await tick();
	assert.equal(calls.length, 0);
	search.update('lam');
	search.update(' lamine ', 4);
	await tick();
	assert.deepEqual(calls, ['/api/search?q=lamine&pos=4']);
	assert.deepEqual(state, { results: ['Lamine'], loading: false, error: false });
	search.destroy();
});

test('a late response cannot replace a newer search, even if abort is ignored', async () => {
	let finishOld!: (value: Response) => void;
	let state: SearchState<string> | undefined;
	let oldSignal: AbortSignal | null | undefined;
	const search = createPlayerSearch<string>((next) => { state = next; }, {
		delay: 0, fetch: async (url, init) => {
			if (String(url).includes('lamine')) {
				oldSignal = init?.signal;
				return new Promise((resolve) => { finishOld = resolve; });
			}
			return response('Soria');
		}
	});
	search.update('lamine'); await tick();
	search.update('soria'); await tick();
	assert.equal(oldSignal?.aborted, true);
	finishOld(response('Lamine')); await tick();
	assert.deepEqual(state?.results, ['Soria']);
	search.destroy();
});

test('errors can retry, and clearing removes results and pending searches', async () => {
	let fail = true;
	let calls = 0;
	let state: SearchState<string> | undefined;
	const search = createPlayerSearch<string>((next) => { state = next; }, {
		delay: 0, fetch: async () => { calls++; return fail ? new Response('', { status: 500 }) : response('Soria'); }
	});
	search.update('soria'); await tick();
	assert.equal(state?.error, true);
	fail = false;
	search.update('soria'); await tick();
	assert.deepEqual(state, { results: ['Soria'], loading: false, error: false });
	search.update('lamine'); search.reset(); await tick();
	assert.equal(calls, 2);
	assert.deepEqual(state, { results: [], loading: false, error: false });
	search.destroy();
});
