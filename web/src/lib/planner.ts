// Simulación local de operaciones. Los xPts llegan del cálculo Python; aquí solo se elige
// el mejor once entre las siete formaciones oficiales para una plantilla hipotética.
export const FORMATIONS = [
	[5, 4, 1], [5, 3, 2], [4, 5, 1], [4, 4, 2], [4, 3, 3], [3, 5, 2], [3, 4, 3]
] as const;

export type PlannerPlayer = {
	player_id: string;
	name: string;
	position_id: number;
	xpts: number | null;
	unavailable: boolean;
};

export type PlannerBuy = PlannerPlayer & { min_price: number };
export type Choice = { player_id: string; amount: number };
export type ProjectedEleven = {
	formation: string;
	starters: PlannerPlayer[];
	xpts: number;
	feasible: number;
};

const POSITION_NAMES = ['portero', 'defensa', 'medio', 'delantero'];
const POSITION_PLURALS = ['porteros', 'defensas', 'medios', 'delanteros'];
const available = (p: PlannerPlayer) => !p.unavailable && p.position_id >= 1 && p.position_id <= 4;

export function feasibleFormations(players: PlannerPlayer[]): string[] {
	const counts = [1, 2, 3, 4].map((pos) => players.filter((p) => available(p) && p.position_id === pos).length);
	return FORMATIONS.flatMap(([d, m, f]) =>
		counts[0] >= 1 && counts[1] >= d && counts[2] >= m && counts[3] >= f ? [`${d}-${m}-${f}`] : []
	);
}

export function missingForEleven(players: PlannerPlayer[]): string[] {
	const counts = [1, 2, 3, 4].map((pos) => players.filter((p) => available(p) && p.position_id === pos).length);
	const options = FORMATIONS.map(([d, m, f]) => [1, d, m, f].map((n, index) => Math.max(0, n - counts[index])));
	const total = (counts: number[]) => counts.reduce((sum, n) => sum + n, 0);
	const minimum = Math.min(...options.map(total));
	if (!minimum) return [];
	const shortest = options.filter((option) => total(option) === minimum);
	// Varias posiciones pueden completar el mismo once. No señalar una sola como obligatoria.
	const unambiguous = shortest.every((option) => option.every((count, index) => count === shortest[0][index]));
	if (!unambiguous) return [`${minimum} ${minimum === 1 ? 'jugador' : 'jugadores'} para completar una formación`];
	return shortest[0].flatMap((count, index) => count ? [`${count} ${count === 1 ? POSITION_NAMES[index] : POSITION_PLURALS[index]}`] : []);
}

export function bestEleven(players: PlannerPlayer[]): ProjectedEleven | null {
	const eligible = players.filter(available);
	if (missingForEleven(eligible).length || eligible.some((p) => p.xpts == null)) return null;
	const byPos = [1, 2, 3, 4].map((pos) =>
		eligible.filter((p) => p.position_id === pos).sort((a, b) => (b.xpts ?? 0) - (a.xpts ?? 0))
	);
	let best: ProjectedEleven | null = null;
	let feasible = 0;
	for (const [d, m, f] of FORMATIONS) {
		if (byPos[0].length < 1 || byPos[1].length < d || byPos[2].length < m || byPos[3].length < f) continue;
		feasible++;
		const starters = [...byPos[0].slice(0, 1), ...byPos[1].slice(0, d), ...byPos[2].slice(0, m), ...byPos[3].slice(0, f)];
		const xpts = starters.reduce((sum, p) => sum + (p.xpts ?? 0), 0);
		if (!best || xpts > best.xpts) best = { formation: `${d}-${m}-${f}`, starters, xpts, feasible: 0 };
	}
	return best ? { ...best, feasible } : null;
}

export function projectScenario(
	roster: PlannerPlayer[],
	market: PlannerBuy[],
	startingCash: number,
	buys: Choice[],
	sells: Choice[]
) {
	const rosterById = new Map(roster.map((p) => [p.player_id, p]));
	const marketById = new Map(market.map((p) => [p.player_id, p]));
	const errors: string[] = [];
	if (new Set(buys.map((c) => c.player_id)).size !== buys.length || new Set(sells.map((c) => c.player_id)).size !== sells.length) {
		errors.push('Hay un jugador repetido en el escenario.');
	}
	for (const c of sells) {
		if (!rosterById.has(c.player_id)) errors.push('Una venta ya no pertenece a tu plantilla.');
		if (!Number.isFinite(c.amount) || c.amount < 0) errors.push('Revisa el importe de una venta.');
	}
	for (const c of buys) {
		const player = marketById.get(c.player_id);
		if (!player || rosterById.has(c.player_id)) errors.push('Un fichaje ya no está disponible en el mercado.');
		if (!Number.isFinite(c.amount) || c.amount < (player?.min_price ?? 0)) errors.push('Una compra está por debajo del precio anunciado.');
	}
	const spent = buys.reduce((sum, c) => sum + (Number.isFinite(c.amount) ? c.amount : 0), 0);
	const proceeds = sells.reduce((sum, c) => sum + (Number.isFinite(c.amount) ? c.amount : 0), 0);
	const cashAfter = startingCash + proceeds - spent;
	const soldIds = new Set(sells.map((c) => c.player_id));
	const projectedRoster = [
		...roster.filter((p) => !soldIds.has(p.player_id)),
		...buys.flatMap((c) => {
			const player = marketById.get(c.player_id);
			return player && !rosterById.has(c.player_id) ? [player] : [];
		})
	];
	const missing = missingForEleven(projectedRoster);
	const unknown = projectedRoster.filter((p) => available(p) && p.xpts == null).map((p) => p.name);
	const before = bestEleven(roster);
	const after = errors.length ? null : bestEleven(projectedRoster);
	const beforeIds = new Set(before?.starters.map((p) => p.player_id) ?? []);
	const afterIds = new Set(after?.starters.map((p) => p.player_id) ?? []);
	return {
		cashAfter, spent, proceeds, before, after, missing, unknown, errors,
		formations: feasibleFormations(projectedRoster),
		enters: after?.starters.filter((p) => !beforeIds.has(p.player_id)) ?? [],
		exits: before?.starters.filter((p) => !afterIds.has(p.player_id)) ?? []
	};
}
