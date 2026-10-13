import { error } from '@sveltejs/kit';
import { market, myTeam, plannerSquadSignals, recommendations, squad } from '$lib/server/queries';
import type { PlannerBuy, PlannerPlayer } from '$lib/planner';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async () => {
	const [team, offers, recs] = await Promise.all([myTeam(), market(), recommendations()]);
	if (!team) error(404, 'Sin datos de tu liga todavía');
	const [sq, signals] = await Promise.all([squad(team.team_id), plannerSquadSignals(team.team_id)]);
	const buyRecs = new Map(recs.filter((r) => r.kind === 'buy').map((r) => [r.player_id, r]));
	const sellRecs = new Map(recs.filter((r) => r.kind === 'sell').map((r) => [r.player_id, r]));
	const owned = new Set(sq.players.map((p) => p.player_id));
	const roster: (PlannerPlayer & { value: number; club: string; status: string })[] = sq.players.map((p) => {
		const signal = signals.get(p.player_id);
		return {
			player_id: p.player_id,
			name: p.nickname || p.name,
			value: p.value,
			club: p.club,
			status: p.status,
			position_id: p.position_id,
			xpts: sellRecs.get(p.player_id)?.xpts ?? signal?.xpts ?? null,
			unavailable: p.status === 'injured' || p.status === 'suspended' || p.status === 'out_of_league' ||
				!!signal?.injured || !!signal?.suspended
		};
	});
	const candidates: (PlannerBuy & {
		ask: number; suggested: number; verdict: string | null; max_bid: number | null; kind: string; club: string;
	})[] = offers
		.filter((p) => !p.mine && !owned.has(p.player_id) && p.position_id >= 1 && p.position_id <= 4 && p.status !== 'out_of_league')
		.map((p) => {
			const rec = buyRecs.get(p.player_id);
			return {
				player_id: p.player_id,
				name: p.nickname || p.name,
				position_id: p.position_id,
				xpts: rec?.xpts ?? null,
				unavailable: p.status === 'injured' || p.status === 'suspended' || !!p.injured || !!p.suspended,
				min_price: p.sale_price,
				ask: p.sale_price,
				suggested: rec?.verdict === 'pujar' ? Math.max(p.sale_price, rec.bid_to_win ?? 0) : p.sale_price,
				verdict: rec?.verdict ?? null,
				max_bid: rec?.max_bid ?? null,
				kind: p.kind,
				club: p.club
			};
		})
		.sort((a, b) => (a.verdict === 'pujar' ? -1 : 0) - (b.verdict === 'pujar' ? -1 : 0) || a.ask - b.ask);
	return {
		cash: team.team_money,
		roster,
		candidates,
		recommendationsAt: recs[0]?.created_at ?? null
	};
};
