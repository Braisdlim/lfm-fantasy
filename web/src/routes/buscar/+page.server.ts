import { searchPlayers } from '$lib/server/queries';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ url }) => {
	const q = (url.searchParams.get('q') ?? '').trim();
	const pos = Number(url.searchParams.get('pos')) || 0;
	const sort = (url.searchParams.get('sort') as 'valor' | 'puntos' | 'subida') || 'valor';
	const results = await searchPlayers(q, 40, { positionId: pos, sortBy: sort });
	return { q, pos, sort, results };
};
