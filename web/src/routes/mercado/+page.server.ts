import { accuracy, bargains, calendar, market, movers, myListings, myTeam, recommendations, rivalRadar, squadSellAdvisor, topPicksByPriceTier } from '$lib/server/queries';
import { KIND_LEAGUE, KIND_TEAM } from '$lib/format';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async () => {
	const [team, cal, onSale, radar, recs, chollos, acierto, picks, rivals] = await Promise.all([
		myTeam(),
		calendar(),
		market(),
		movers(40, { includeMine: true }),
		recommendations(),
		bargains(),
		accuracy(),
		topPicksByPriceTier(12),
		rivalRadar()
	]);
	const [listings, sellAdvisor] = await Promise.all([
		team ? myListings(team.team_id) : [],
		team ? squadSellAdvisor(team.team_id) : null
	]);
	// Quién podría disputarte cada jugador de la liga: le falta esa posición y le llega el saldo.
	const contenders: Record<string, string[]> = {};
	for (const r of rivals) for (const b of r.could_bid) (contenders[b.player_id] ??= []).push(r.manager_name);
	return {
		contenders,
		team,
		closesAt: cal.closesAt,
		league: onSale.filter((m) => m.kind === KIND_LEAGUE),
		managers: onSale.filter((m) => m.kind === KIND_TEAM && !m.mine),
		listings,
		radar,
		recs,
		chollos,
		acierto,
		picks,
		sellAdvisor
	};
};
