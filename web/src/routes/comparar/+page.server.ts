import { comparisonPlayers, searchPlayers } from '$lib/server/queries';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ url }) => {
	const p1Id = url.searchParams.get('p1');
	const p2Id = url.searchParams.get('p2');
	const players = await comparisonPlayers([...new Set([p1Id, p2Id].filter((id): id is string => !!id))]);
	const p1 = p1Id ? players.get(p1Id) ?? null : null;
	const p2 = p2Id ? players.get(p2Id) ?? null : null;

	// Sugerencias inteligentes: si hay p1 pero no p2, sugerimos rivales de la misma posición
	let suggestions: Awaited<ReturnType<typeof searchPlayers>> = [];
	if (p1 && !p2) {
		const raw = await searchPlayers('', 15, {
			positionId: p1.card.position_id,
			sortBy: 'puntos'
		});
		suggestions = raw.filter((s) => s.player_id !== p1.card.player_id).slice(0, 10);
	} else if (!p1 && !p2) {
		suggestions = (await searchPlayers('', 10, { sortBy: 'puntos' })).slice(0, 8);
	}

	return {
		p1,
		p2,
		p1Id,
		p2Id,
		suggestions
	};
};
