<script lang="ts">
	// Quién lanza el balón parado de su equipo. Los números salen de FútbolFantasy, codificados
	// como (aciertos + 1) * 1000 + intentos, y el total del club viene de `team_set_pieces`: sumar
	// solo a los jugadores casados dejaba a la Real Sociedad en 18 córners en vez de 24 y le
	// inflaba el porcentaje a todos sus compañeros.
	import { shortClub } from '$lib/format';
	import type { PlayerSetPieces } from '$lib/server/queries';
	let { sp, club }: { sp: PlayerSetPieces; club: string } = $props();
	const equipo = $derived(shortClub(club));
	const plural = (n: number, uno: string, varios: string) => `${n} ${n === 1 ? uno : varios}`;

	type Fila = { que: string; suyos: number; equipo: number; nota: string };
	const filas = $derived(
		(
			[
				{ que: 'Penaltis', suyos: sp.pen_taken, equipo: sp.team_pen, nota: plural(sp.pen_scored, 'marcado', 'marcados') },
				{ que: 'Córners', suyos: sp.corner_taken, equipo: sp.team_corner, nota: plural(sp.corner_accurate, 'bueno', 'buenos') },
				{ que: 'Faltas al área', suyos: sp.cross_taken, equipo: sp.team_cross, nota: plural(sp.cross_accurate, 'buena', 'buenas') },
				{ que: 'Faltas directas', suyos: sp.fk_taken, equipo: sp.team_fk, nota: `${sp.fk_on_target} a puerta` }
			] as Fila[]
		).filter((f) => f.suyos > 0)
	);

	const parte = (f: Fila) => (f.equipo > 0 ? f.suyos / f.equipo : 0);

	/** Una sola conclusión, la que más manda: el penalti pesa más que el córner. */
	const conclusion = $derived.by(() => {
		if (sp.pen_taken > 0 && sp.pen_taken >= sp.team_pen)
			return `Lanza los penaltis del ${equipo}: ha tirado los ${sp.pen_taken} que han tenido y ha marcado ${sp.pen_scored}.`;
		if (sp.pen_taken > 0)
			return `Ha lanzado ${sp.pen_taken} de los ${sp.team_pen} penaltis del ${equipo}, así que los reparte.`;
		const c = Math.round(parte({ que: '', suyos: sp.corner_taken, equipo: sp.team_corner, nota: '' }) * 100);
		if (sp.corner_top && c >= 50) return `Es el lanzador de córners del ${equipo}: saca ${c} de cada 100.`;
		if (sp.corner_top) return `Es el que más córners saca del ${equipo}, ${c} de cada 100, pero los reparte con otro.`;
		if (c > 0) return `Saca ${c} de cada 100 córners del ${equipo}; hay algún compañero que saca más.`;
		return `Lanza alguna falta del ${equipo}, pero ni los penaltis ni los córners.`;
	});
</script>

<div class="p-3">
	<p class="mb-3 text-sm leading-snug">{conclusion}</p>
	<div class="space-y-2">
		{#each filas as f (f.que)}
			<div>
				<div class="flex items-baseline gap-2 text-xs">
					<span class="text-muted flex-1">{f.que}</span>
					<!-- La mono, solo en las cifras: «de 21 del equipo» en monoespaciada se lee peor. -->
					<span><span class="num font-semibold">{f.suyos}</span> de <span class="num">{f.equipo}</span> del equipo</span>
					<span class="text-muted w-24 text-right">{f.nota}</span>
				</div>
				<div class="bg-surface-2 mt-1 h-1 overflow-hidden rounded-full">
					<div class="bg-accent h-full" style="width: {Math.round(parte(f) * 100)}%"></div>
				</div>
			</div>
		{/each}
	</div>
	<p class="text-muted mt-3 text-[11px] leading-snug">
		De lo que va de temporada. Los córners contados son los que se cuelgan al área: los que se
		sacan en corto van aparte y la fuente no los reparte por jugador.
	</p>
</div>
