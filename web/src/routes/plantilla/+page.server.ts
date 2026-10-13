import { error } from '@sveltejs/kit';
import { eleven, myTeam, squad, squadSellAdvisor } from '$lib/server/queries';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async () => {
	const team = await myTeam();
	if (!team) error(404, 'Sin datos de tu liga todavía');
	const [sq, once, sellAdvisor] = await Promise.all([
		squad(team.team_id),
		eleven(team.team_id),
		squadSellAdvisor(team.team_id)
	]);
	return { team: { ...team, ...sq.team }, players: sq.players, once, sellAdvisor };
};
