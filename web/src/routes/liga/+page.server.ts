import { activity, clauses, myTeam, rivalRadar, standing, threats } from '$lib/server/queries';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async () => {
	const [team, table, cls, feed, radar] = await Promise.all([myTeam(), standing(), clauses(), activity(40), rivalRadar()]);
	const th = team ? await threats(team.team_id) : [];
	return { team, table, clauses: cls, feed, threats: th, radar };
};
