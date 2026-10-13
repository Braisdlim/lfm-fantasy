import { freshness, latestDay, myTeam } from '$lib/server/queries';
import type { LayoutServerLoad } from './$types';
import { env } from '$env/dynamic/private';

export const load: LayoutServerLoad = async ({ url }) => {
	if (url.pathname === '/login') return { team: undefined, latest: null, fresh: null };
	const [team, latest, fresh] = await Promise.all([myTeam(), latestDay(), freshness()]);
	return { team, latest, fresh, demo: env.DEMO_MODE === 'true' };
};
