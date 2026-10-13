import { myTeam, watchlist } from '$lib/server/queries';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async () => {
	const [team, items] = await Promise.all([myTeam(), watchlist()]);
	return { team, items };
};
