import assert from 'node:assert/strict';
import test from 'node:test';
import { parseMillions, parseWatchForm } from '../src/lib/watch-form.ts';

const fd = (o: Record<string, string>) => {
	const f = new FormData();
	for (const [k, v] of Object.entries(o)) f.set(k, v);
	return f;
};

test('importes en millones con coma, punto o sufijo M', () => {
	assert.equal(parseMillions('5,5'), 5_500_000);
	assert.equal(parseMillions('12.25'), 12_250_000);
	assert.equal(parseMillions('3 M'), 3_000_000);
	assert.equal(parseMillions(''), null);
	assert.equal(parseMillions('-2'), 'invalid');
	assert.equal(parseMillions('abc'), 'invalid');
});

test('titularidad en porcentaje y al menos una vía', () => {
	const ok = parseWatchForm(fd({ max_price: '4', min_start: '60', watch_market: 'on' }));
	assert.ok(ok.ok);
	if (ok.ok) {
		assert.equal(ok.rule.max_price, 4_000_000);
		assert.equal(ok.rule.min_start_prob, 0.6);
		assert.equal(ok.rule.watch_clause, false);
	}
	const none = parseWatchForm(fd({ max_price: '4' }));
	assert.equal(none.ok, false);
	const zero = parseWatchForm(fd({ min_start: '0', watch_clause: 'on' }));
	assert.ok(zero.ok && zero.rule.min_start_prob === null && zero.rule.max_price === null);
});
