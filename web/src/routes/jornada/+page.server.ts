import { calendar, fixtures, ownedByTeam } from '$lib/server/queries';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async () => {
	const [cal, fx, owned] = await Promise.all([calendar(), fixtures(), ownedByTeam()]);
	return { week: cal.week, fixtures: fx, owned };
};
