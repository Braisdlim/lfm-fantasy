import { calendar, clauses, journal, market, movers, myTeam, recommendations, squad, threats, watchlist, type ClauseRow } from '$lib/server/queries';
import { journalSummary } from '$lib/journal';
import type { PageServerLoad } from './$types';

function isOpen(c: { clause_locked_until: string | null; is_shielded: boolean | null }, now: number) {
	return !c.is_shielded && (!c.clause_locked_until || new Date(c.clause_locked_until).getTime() <= now);
}

export const load: PageServerLoad = async () => {
	const now = Date.now();
	const [team, cal, mv, cls, mk, recs, wl, jr] = await Promise.all([
		myTeam(), calendar(), movers(5), clauses(), market(), recommendations(), watchlist(), journal()
	]);
	const [sq, th] = team ? await Promise.all([squad(team.team_id), threats(team.team_id)]) : [{ team: undefined, players: [] }, []];
	const money = team?.team_money ?? 0;
	const buys = recs.filter((r) => r.kind === 'buy' && r.verdict === 'pujar');
	const sells = recs.filter((r) => r.kind === 'sell' && r.verdict === 'vender');
	const actions = (money < 0 ? [...sells, ...buys] : [...buys, ...sells]).slice(0, 3);
	const missingEleven = recs.find((r) => r.missing_eleven?.length)?.missing_eleven ?? [];

	const squadDelta = sq.players.reduce((acc, p) => acc + (p.value_1d != null ? p.value - p.value_1d : 0), 0);
	const squadValue = sq.players.reduce((acc, p) => acc + p.value, 0);
	const byDelta = [...sq.players].filter((p) => p.value_1d != null).sort((a, b) => b.value - b.value_1d! - (a.value - a.value_1d!));

	// Todas las cláusulas ajenas abiertas, se puedan pagar hoy o no: la página filtra por saldo,
	// precio y posición. Antes solo llegaban las 6 que cabían en el saldo y no había forma de ver a
	// cuánto estaba el resto (útil para saber cuánto vender antes de ir a por una).
	const opportunities = cls
		.filter((c) => !c.owner_is_me && isOpen(c, now) && c.status !== 'out_of_league')
		.sort((a, b) => b.gap - a.gap);
	const affordableSoon = cls
		.filter(
			(c) =>
				!c.owner_is_me &&
				!isOpen(c, now) &&
				!c.is_shielded &&
				c.status !== 'out_of_league' &&
				c.clause_locked_until &&
				new Date(c.clause_locked_until).getTime() - now < 72 * 36e5
		)
		.sort((a, b) => new Date(a.clause_locked_until!).getTime() - new Date(b.clause_locked_until!).getTime());

	// mis cláusulas ordenadas por urgencia, con los rivales que podrían pagarlas
	const threatBy = new Map(th.map((t) => [t.player_id, t.threats]));
	const risks: (ClauseRow & { hours: number; threats: { manager_name: string; cash_estimate: number }[] })[] = cls
		.filter((c) => c.owner_is_me && !c.is_shielded)
		.map((c) => ({
			...c,
			hours: c.clause_locked_until ? (new Date(c.clause_locked_until).getTime() - now) / 36e5 : -1,
			threats: threatBy.get(c.player_id) ?? []
		}))
		.filter((c) => c.hours < 72 && c.threats.length > 0)
		.sort((a, b) => b.threats.length - a.threats.length || a.hours - b.hours);

	// La protección mira la jornada en curso; la cuenta atrás del once, la siguiente a preparar.
	const protectionStart = cal.current?.opening_at
		? new Date(new Date(cal.current.opening_at).getTime() - 24 * 36e5).toISOString()
		: null;
	const protectedNow = !!(
		protectionStart &&
		cal.current?.closing_at &&
		now >= new Date(protectionStart).getTime() &&
		now <= new Date(cal.current.closing_at).getTime()
	);

	return {
		team,
		actions,
		missingEleven,
		actionsAt: recs[0]?.created_at ?? null,
		cal,
		protectionStart,
		protectedNow,
		squadValue,
		squadDelta,
		// La línea que separa los dos grupos sugiere "suben / bajan", así que el segundo grupo solo
		// puede llevar los que bajan de verdad. Antes era `slice(-3)` a secas y metía ahí subidas
		// (Hector Fort con +24 k aparecía bajo el separador).
		squadUp: byDelta.filter((p) => p.value > p.value_1d!).slice(0, 3),
		squadDown: byDelta.filter((p) => p.value < p.value_1d!).slice(-3).reverse(),
		notPlaying: sq.players.filter((p) => p.status !== 'ok'),
		opportunities,
		affordableSoon,
		risks,
		marketCount: mk.length,
		marketMine: mk.filter((m) => m.mine),
		marketHot: mk.filter((m) => m.value_1d != null).slice(0, 3),
		movers: mv,
		watchReady: wl.filter((w) => w.state === 'cumple'),
		watchCount: wl.length,
		diary: jr.entries.length ? journalSummary(jr.entries) : null
	};
};
