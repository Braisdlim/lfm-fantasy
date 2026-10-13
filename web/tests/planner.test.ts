import assert from 'node:assert/strict';
import test from 'node:test';
import { bestEleven, FORMATIONS, missingForEleven, projectScenario, type PlannerBuy, type PlannerPlayer } from '../src/lib/planner.ts';

const p = (id: string, pos: number, xpts: number | null, unavailable = false): PlannerPlayer => ({
	player_id: id, name: id, position_id: pos, xpts, unavailable
});
const buy = (id: string, pos: number, xpts: number | null, min_price: number): PlannerBuy => ({
	...p(id, pos, xpts), min_price
});
const roster = () => [
	p('g', 1, 5), p('d1', 2, 4), p('d2', 2, 4), p('d3', 2, 4),
	p('m1', 3, 3), p('m2', 3, 3), p('m3', 3, 3), p('m4', 3, 3),
	p('f1', 4, 2), p('f2', 4, 2), p('f3', 4, 2)
];

test('the planner uses exactly the seven formations allowed by the game', () => {
	assert.deepEqual(FORMATIONS, [[5, 4, 1], [5, 3, 2], [4, 5, 1], [4, 4, 2], [4, 3, 3], [3, 5, 2], [3, 4, 3]]);
	assert.equal(bestEleven(roster())?.formation, '3-4-3');
});

test('two purchases and one sale recalculate cash and the best formation together', () => {
	const result = projectScenario(roster(), [buy('d4', 2, 9, 8_000_000), buy('m5', 3, 8, 10_000_000)],
		15_000_000, [{ player_id: 'd4', amount: 8_000_000 }, { player_id: 'm5', amount: 10_000_000 }],
		[{ player_id: 'f3', amount: 4_000_000 }]);
	assert.equal(result.cashAfter, 1_000_000);
	assert.equal(result.before?.xpts, 35);
	assert.equal(result.after?.formation, '4-5-1');
	assert.equal(result.after?.xpts, 48);
	assert.deepEqual(result.enters.map((x) => x.player_id).sort(), ['d4', 'm5']);
	assert.deepEqual(result.exits.map((x) => x.player_id).sort(), ['f2', 'f3']);
});

test('a purchase can make an incomplete squad alignable', () => {
	const withoutMid = roster().filter((x) => x.player_id !== 'm4');
	assert.deepEqual(missingForEleven(withoutMid), ['1 jugador para completar una formación']);
	const result = projectScenario(withoutMid, [buy('m5', 3, 7, 2_000_000)], 3_000_000,
		[{ player_id: 'm5', amount: 2_000_000 }], []);
	assert.equal(result.before, null);
	assert.equal(result.after?.formation, '3-4-3');
	assert.deepEqual(result.missing, []);
});

test('selling a necessary goalkeeper leaves no valid eleven', () => {
	const result = projectScenario(roster(), [], 0, [], [{ player_id: 'g', amount: 5_000_000 }]);
	assert.equal(result.after, null);
	assert.deepEqual(result.missing, ['1 portero']);
});

test('an unknown xPts or unavailable player is never treated as a zero-point starter', () => {
	const unknown = roster();
	unknown[1] = p('d1', 2, null);
	assert.equal(bestEleven(unknown), null);
	const injured = roster();
	injured[0] = p('g', 1, 5, true);
	assert.deepEqual(missingForEleven(injured), ['1 portero']);
});

test('below-ask purchases and a negative balance are reported separately', () => {
	const invalid = projectScenario(roster(), [buy('star', 3, 8, 5_000_000)], 3_000_000,
		[{ player_id: 'star', amount: 4_000_000 }], []);
	assert.equal(invalid.cashAfter, -1_000_000);
	assert.equal(invalid.after, null);
	assert.match(invalid.errors.join(' '), /debajo del precio anunciado/);
});
