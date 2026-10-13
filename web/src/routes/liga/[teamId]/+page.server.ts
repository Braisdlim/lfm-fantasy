import { error } from '@sveltejs/kit';
import { myTeam, rivalRadar, squad } from '$lib/server/queries';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params }) => {
	const [me, sq, radar] = await Promise.all([myTeam(), squad(params.teamId), rivalRadar()]);
	if (!sq.team) error(404, 'Equipo no encontrado');
	return { me, team: sq.team, players: sq.players, radar: radar.find((r) => r.team_id === params.teamId) ?? null };
};
