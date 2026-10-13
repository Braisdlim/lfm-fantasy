import { json } from '@sveltejs/kit';
import { searchPlayers } from '$lib/server/queries';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = async ({ url }) => {
	const q = url.searchParams.get('q') ?? '';
	const pos = Number(url.searchParams.get('pos')) || undefined;
	const results = await searchPlayers(q, 20, { positionId: pos });
	return json({ results });
};
