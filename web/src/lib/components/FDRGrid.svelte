<script lang="ts">
	import {
		calculateFDR,
		FDR_STYLES,
		fdrAvgBadge,
		fixed,
		matchDay,
		matchTime,
		POS,
		shortClub,
		type FDRMode,
		type FDRLevel
	} from '$lib/format';
	import type { Match, SquadByTeam } from '$lib/server/queries';

	let { fixtures, owned }: { fixtures: Match[]; owned: SquadByTeam[] } = $props();

	type Mode = FDRMode;
	type Range = 3 | 5 | 8 | 0;
	type Sort = 'fdr' | 'tuyos' | 'alpha';

	let mode = $state<Mode>('general');
	let range = $state<Range>(5);
	let sortBy = $state<Sort>('fdr');

	export type FixtureSide = {
		match_id: string;
		week: number;
		date: string | null;
		team_id: string;
		team: string;
		team_badge: string | null;
		rival_id: string;
		rival: string;
		rival_badge: string | null;
		home: boolean;
		xg_for: number;
		xg_against: number;
		cs_prob: number;
		p_win: number | null;
		p_draw: number | null;
		p_loss: number | null;
		played: boolean;
		marcador: string | null;
	};

	let selectedMatch = $state<FixtureSide | null>(null);

	// Jugadores del usuario por club
	const mios = $derived.by(() => {
		const m = new Map<string, SquadByTeam[]>();
		for (const p of owned.filter((p) => p.mine)) {
			if (!m.has(p.team_id)) m.set(p.team_id, []);
			m.get(p.team_id)!.push(p);
		}
		return m;
	});

	// Todas las jornadas disponibles
	const allWeeks = $derived([...new Set(fixtures.map((f) => f.week))].sort((a, b) => a - b));

	// Genera los botones de rango dinámicamente según las jornadas realmente disponibles
	const availableRanges = $derived.by(() => {
		const total = allWeeks.length;
		const r: { val: number; label: string }[] = [];
		if (total >= 3) r.push({ val: 3, label: '3 J' });
		if (total >= 5) r.push({ val: 5, label: '5 J' });
		if (total >= 8) r.push({ val: 8, label: '8 J' });
		r.push({ val: 0, label: `Todas (${total})` });
		return r;
	});

	// Semanas dentro del rango seleccionado
	const selectedWeeks = $derived.by(() => {
		if (range > 0) return allWeeks.slice(0, range);
		return allWeeks;
	});

	// Procesa los datos por club y calcula el FDR
	const processed = $derived.by(() => {
		const weeks = selectedWeeks;
		const clubesMap = new Map<
			string,
			{
				team: string;
				badge_url: string | null;
				casillas: (FixtureSide | null)[];
			}
		>();

		for (const f of fixtures) {
			if (!weeks.includes(f.week)) continue;
			const colIndex = weeks.indexOf(f.week);
			const jugado = f.local_score != null && f.visitor_score != null;

			// Lado Local
			if (!clubesMap.has(f.local_id)) {
				clubesMap.set(f.local_id, {
					team: f.local,
					badge_url: f.local_badge,
					casillas: weeks.map(() => null)
				});
			}
			clubesMap.get(f.local_id)!.casillas[colIndex] = {
				match_id: f.match_id,
				week: f.week,
				date: f.date,
				team_id: f.local_id,
				team: f.local,
				team_badge: f.local_badge,
				rival_id: f.visitor_id,
				rival: f.visitor,
				rival_badge: f.visitor_badge,
				home: true,
				xg_for: f.xg_local ?? 0,
				xg_against: f.xg_visitor ?? 0,
				cs_prob: f.cs_local ?? 0,
				p_win: f.p_local,
				p_draw: f.p_draw,
				p_loss: f.p_visitor,
				played: jugado,
				marcador: jugado ? `${f.local_score}-${f.visitor_score}` : null
			};

			// Lado Visitante
			if (!clubesMap.has(f.visitor_id)) {
				clubesMap.set(f.visitor_id, {
					team: f.visitor,
					badge_url: f.visitor_badge,
					casillas: weeks.map(() => null)
				});
			}
			clubesMap.get(f.visitor_id)!.casillas[colIndex] = {
				match_id: f.match_id,
				week: f.week,
				date: f.date,
				team_id: f.visitor_id,
				team: f.visitor,
				team_badge: f.visitor_badge,
				rival_id: f.local_id,
				rival: f.local,
				rival_badge: f.local_badge,
				home: false,
				xg_for: f.xg_visitor ?? 0,
				xg_against: f.xg_local ?? 0,
				cs_prob: f.cs_visitor ?? 0,
				p_win: f.p_visitor,
				p_draw: f.p_draw,
				p_loss: f.p_local,
				played: jugado,
				marcador: jugado ? `${f.visitor_score}-${f.local_score}` : null
			};
		}

		// Lista enriquecida con promedio de FDR y jugadores del usuario
		const list = [...clubesMap.entries()].map(([id, item]) => {
			const unplayedScores: number[] = [];
			for (const c of item.casillas) {
				if (c && !c.played) {
					const f = calculateFDR(c.xg_for, c.xg_against, c.cs_prob, mode);
					unplayedScores.push(f.score);
				}
			}
			const avg = unplayedScores.length
				? unplayedScores.reduce((a, b) => a + b, 0) / unplayedScores.length
				: 3.0;

			return {
				id,
				team: item.team,
				badge_url: item.badge_url,
				casillas: item.casillas,
				tuyos: mios.get(id)?.length ?? 0,
				fdrAvg: avg
			};
		});

		// Ordenación
		if (sortBy === 'fdr') {
			list.sort((a, b) => a.fdrAvg - b.fdrAvg || b.tuyos - a.tuyos || a.team.localeCompare(b.team));
		} else if (sortBy === 'tuyos') {
			list.sort((a, b) => b.tuyos - a.tuyos || a.fdrAvg - b.fdrAvg || a.team.localeCompare(b.team));
		} else {
			list.sort((a, b) => a.team.localeCompare(b.team));
		}

		return { weeks, list };
	});

	// Jugadores del usuario en el partido seleccionado para el modal
	const playersInSelected = $derived.by(() => {
		if (!selectedMatch) return [];
		const teamPlayers = mios.get(selectedMatch.team_id) ?? [];
		const rivalPlayers = mios.get(selectedMatch.rival_id) ?? [];
		return [
			...teamPlayers.map((p) => ({ ...p, isTeam: true })),
			...rivalPlayers.map((p) => ({ ...p, isTeam: false }))
		];
	});
</script>

<!-- Panel de Controles: Modo, Rango y Orden -->
<div class="space-y-2.5 pt-1 pb-3">
	<!-- 1. Modos: General, Ataque, Defensa -->
	<div class="bg-surface-2 flex rounded-xl p-1 text-xs font-semibold">
		<button
			type="button"
			onclick={() => (mode = 'general')}
			class="flex-1 rounded-lg py-1.5 text-center transition-colors cursor-pointer {mode === 'general'
				? 'bg-surface font-bold text-fg shadow-xs'
				: 'text-muted hover:text-fg'}"
		>
			Balance General
		</button>
		<button
			type="button"
			onclick={() => (mode = 'attack')}
			class="flex-1 rounded-lg py-1.5 text-center transition-colors cursor-pointer {mode === 'attack'
				? 'bg-surface font-bold text-fg shadow-xs'
				: 'text-muted hover:text-fg'}"
		>
			Ataque (Goles)
		</button>
		<button
			type="button"
			onclick={() => (mode = 'defense')}
			class="flex-1 rounded-lg py-1.5 text-center transition-colors cursor-pointer {mode === 'defense'
				? 'bg-surface font-bold text-fg shadow-xs'
				: 'text-muted hover:text-fg'}"
		>
			Defensa (Portería a cero)
		</button>
	</div>

	<!-- 2. Rango de Jornadas y Selector de Ordenación -->
	<div class="flex items-center justify-between gap-2 text-xs">
		<!-- Selector de Rango -->
		<div class="flex items-center gap-1 overflow-x-auto scrollbar-none">
			<span class="text-muted text-[11px] font-medium mr-1">Rango:</span>
			{#each availableRanges as r (r.val)}
				<button
					type="button"
					onclick={() => (range = r.val as Range)}
					class="rounded-lg px-2.5 py-1 text-[11px] font-semibold transition-colors cursor-pointer {range === r.val
						? 'bg-fg text-bg'
						: 'bg-surface-2 text-muted hover:text-fg'}"
				>
					{r.label}
				</button>
			{/each}
		</div>

		<!-- Selector de Orden -->
		<div class="flex items-center gap-1 shrink-0">
			<span class="text-muted text-[11px] font-medium">Orden:</span>
			<button
				type="button"
				onclick={() => {
					if (sortBy === 'fdr') sortBy = 'tuyos';
					else if (sortBy === 'tuyos') sortBy = 'alpha';
					else sortBy = 'fdr';
				}}
				class="rounded-lg bg-surface-2 border border-line px-2.5 py-1 text-[11px] font-semibold text-fg hover:border-fg/40 transition-colors cursor-pointer"
			>
				{sortBy === 'fdr' ? 'Más favorable' : sortBy === 'tuyos' ? 'Tus jugadores' : 'A-Z'}
			</button>
		</div>
	</div>

	<!-- 3. Leyenda FDR interactiva / visual -->
	<div class="flex flex-wrap items-center justify-between gap-1.5 rounded-lg bg-surface-2/40 border border-line/60 px-2.5 py-2 text-[10px]">
		<span class="text-muted font-bold tracking-wider uppercase text-[9px]">Dificultad FDR:</span>
		<div class="flex items-center gap-1 overflow-x-auto">
			{#each [1, 2, 3, 4, 5] as lvl (lvl)}
				{@const st = FDR_STYLES[lvl as FDRLevel]}
				<span class="rounded px-1.5 py-0.5 text-[9px] font-bold border {st.cls}">
					{lvl} {st.label}
				</span>
			{/each}
		</div>
	</div>
</div>

<!-- Rejilla FDR con Columna Sticky para Móvil -->
<div class="rounded-xl border border-line bg-surface overflow-hidden shadow-xs">
	<div class="overflow-x-auto scrollbar-thin">
		<table class="w-full border-collapse text-left text-xs">
			<thead>
				<tr class="bg-surface-2/80 border-b border-line text-[11px] font-bold text-muted uppercase tracking-wider">
					<!-- Columna Fija: Club + FDR Promedio -->
					<th class="sticky left-0 z-20 bg-surface-2/95 backdrop-blur-xs border-r border-line py-2.5 px-2.5 min-w-[7.5rem] sm:min-w-[8.5rem]">
						<div class="flex items-center justify-between">
							<span>Club</span>
							<span class="text-[10px] lowercase font-normal text-muted" title="Media de dificultad en las próximas jornadas">FDR</span>
						</div>
					</th>

					<!-- Columnas de Jornadas -->
					{#each processed.weeks as w (w)}
						<th class="py-2.5 px-1.5 text-center min-w-[4.85rem] border-r border-line/40 last:border-0 font-extrabold text-fg">
							J{w}
						</th>
					{/each}
				</tr>
			</thead>
			<tbody class="divide-y divide-line/60">
				{#each processed.list as c (c.id)}
					{@const avgBadge = fdrAvgBadge(c.fdrAvg)}
					<tr class="hover:bg-surface-2/30 transition-colors {c.tuyos ? 'bg-accent/[0.03]' : ''}">
						<!-- Columna Fija: Escudo + Club + Badge FDR -->
						<td class="sticky left-0 z-10 bg-surface border-r border-line py-2 px-2.5 backdrop-blur-xs shadow-xs">
							<div class="flex items-center justify-between gap-1.5">
								<div class="flex items-center gap-1.5 min-w-0">
									{#if c.badge_url}
										<img src={c.badge_url} alt="" class="h-4 w-4 shrink-0 object-contain" loading="lazy" />
									{:else}
										<span class="h-4 w-4 rounded-full bg-surface-2 shrink-0 text-[9px] flex items-center justify-center font-bold text-muted">
											{c.team.charAt(0)}
										</span>
									{/if}
									<span class="truncate font-semibold text-fg text-xs {c.tuyos ? 'text-accent' : ''}">
										{shortClub(c.team)}
									</span>
									{#if c.tuyos > 0}
										<span class="rounded bg-accent/15 px-1 py-0.2 text-[9px] font-black text-accent shrink-0" title="Tienes {c.tuyos} jugadores de este club">
											{c.tuyos}
										</span>
									{/if}
								</div>

								<!-- FDR Score medio acumulado -->
								<span class="num text-[11px] font-bold px-1.5 py-0.5 rounded shrink-0 {avgBadge.cls}" title="Dificultad media: {c.fdrAvg.toFixed(2)}">
									{c.fdrAvg.toFixed(1)}
								</span>
							</div>
						</td>

						<!-- Celdas de Partidos por Jornada -->
						{#each c.casillas as l (l ? l.match_id + l.team_id : Math.random())}
							<td class="p-1 border-r border-line/40 last:border-0 text-center">
								{#if l}
									{@const fdr = calculateFDR(l.xg_for, l.xg_against, l.cs_prob, mode)}
									<button
										type="button"
										onclick={() => (selectedMatch = l)}
										class="w-full rounded-lg px-1.5 py-1.5 transition-all text-center focus:outline-none cursor-pointer hover:scale-[1.03] active:scale-95
										{l.played ? 'bg-surface-2/70 text-muted border border-line' : fdr.cls}"
									>
										<!-- Fila Superior: C/F + Escudito rival + Nombre rival -->
										<div class="flex items-center justify-center gap-1 text-[11px] leading-none">
											<span class="rounded px-1 py-0.2 text-[8px] font-black uppercase {l.home ? 'bg-black/20 text-fg' : 'bg-accent/25 text-accent'}">
												{l.home ? 'C' : 'F'}
											</span>
											{#if l.rival_badge}
												<img src={l.rival_badge} alt="" class="h-3 w-3 object-contain shrink-0" loading="lazy" />
											{/if}
											<span class="truncate font-bold max-w-[2.4rem]">{shortClub(l.rival)}</span>
										</div>

										<!-- Fila Inferior: Marcador si jugado o Métrica según modo -->
										<div class="mt-1 text-[9px] font-medium leading-none">
											{#if l.played}
												<span class="num font-bold text-fg">{l.marcador}</span>
											{:else if mode === 'attack'}
												<span class="opacity-90">{fixed(l.xg_for, 1)} xG</span>
											{:else if mode === 'defense'}
												<span class="opacity-90">{Math.round(l.cs_prob * 100)}% CS</span>
											{:else}
												<span class="opacity-75 font-semibold">FDR {fdr.score}</span>
											{/if}
										</div>
									</button>
								{:else}
									<div class="text-muted text-[10px] italic py-2">
										descansa
									</div>
								{/if}
							</td>
						{/each}
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
</div>

<!-- Modal / Bottom Sheet con Detalles del Partido al Tocar una Celda -->
{#if selectedMatch}
	{@const sm = selectedMatch}
	{@const fdr = calculateFDR(sm.xg_for, sm.xg_against, sm.cs_prob, mode)}
	<!-- Backdrop -->
	<div class="fixed inset-0 z-50 bg-black/60 backdrop-blur-xs flex items-end sm:items-center justify-center p-0 sm:p-4">
		<!-- Backdrop click to close -->
		<button
			type="button"
			class="absolute inset-0 h-full w-full cursor-default bg-transparent border-none"
			onclick={() => (selectedMatch = null)}
			aria-label="Cerrar modal"
		></button>

		<!-- Contenedor Modal -->
		<div
			class="relative z-10 bg-surface border border-line rounded-t-2xl sm:rounded-2xl w-full max-w-md p-4 space-y-3.5 shadow-2xl animate-in fade-in slide-in-from-bottom-6 duration-200"
			role="dialog"
			aria-modal="true"
		>
			<!-- Cabecera -->
			<div class="flex items-center justify-between border-b border-line pb-2.5">
				<div>
					<span class="text-[10px] font-bold text-muted uppercase tracking-wider">Jornada {sm.week} · {sm.home ? 'En Casa' : 'A Domicilio'}</span>
					<div class="flex items-center gap-2 mt-1">
						{#if sm.team_badge}<img src={sm.team_badge} alt="" class="h-5 w-5 object-contain" />{/if}
						<span class="font-bold text-base text-fg">{sm.team}</span>
						<span class="text-muted text-xs">vs</span>
						{#if sm.rival_badge}<img src={sm.rival_badge} alt="" class="h-5 w-5 object-contain" />{/if}
						<span class="font-bold text-base text-fg">{sm.rival}</span>
					</div>
				</div>
				<button
					type="button"
					onclick={() => (selectedMatch = null)}
					class="rounded-lg bg-surface-2 p-1 text-muted hover:text-fg text-sm cursor-pointer"
					aria-label="Cerrar"
				>
					✕
				</button>
			</div>

			<!-- Nivel FDR del Partido -->
			<div class="rounded-xl border p-2.5 flex items-center justify-between {fdr.cls}">
				<div class="flex items-center gap-2">
					<span class="text-base font-black">Nivel {fdr.score}</span>
					<span class="text-xs font-bold">{fdr.label}</span>
				</div>
				<span class="text-[10px] uppercase font-bold tracking-wider opacity-80">
					{mode === 'attack' ? 'Modo Ataque' : mode === 'defense' ? 'Modo Defensa' : 'Modo General'}
				</span>
			</div>

			<!-- Fecha y Horario -->
			<div class="text-xs text-muted flex items-center justify-between px-1">
				<span>{matchDay(sm.date)} · {matchTime(sm.date)}</span>
				{#if sm.played}
					<span class="rounded bg-surface-2 px-2 py-0.5 font-bold text-fg">Finalizado ({sm.marcador})</span>
				{/if}
			</div>

			<!-- Métricas Clave de Rendimiento Esperado -->
			<div class="grid grid-cols-3 gap-2 text-center text-xs">
				<div class="card bg-surface-2/50 border border-line/60 p-2.5">
					<div class="text-muted text-[10px] font-medium">Goles esperados</div>
					<div class="num text-base font-bold text-fg mt-0.5">{fixed(sm.xg_for, 1)}</div>
					<div class="text-[10px] text-muted">a favor</div>
				</div>
				<div class="card bg-surface-2/50 border border-line/60 p-2.5">
					<div class="text-muted text-[10px] font-medium">Goles rival</div>
					<div class="num text-base font-bold text-fg mt-0.5">{fixed(sm.xg_against, 1)}</div>
					<div class="text-[10px] text-muted">en contra</div>
				</div>
				<div class="card bg-surface-2/50 border border-line/60 p-2.5">
					<div class="text-muted text-[10px] font-medium">Portería a cero</div>
					<div class="num text-base font-bold text-emerald-400 mt-0.5">{Math.round(sm.cs_prob * 100)}%</div>
					<div class="text-[10px] text-muted">clean sheet</div>
				</div>
			</div>

			<!-- Probabilidades de Resultado (si no jugado) -->
			{#if sm.p_win != null}
				<div class="space-y-1">
					<div class="flex justify-between text-[11px] font-medium text-muted">
						<span>Gana {shortClub(sm.team)}: <b class="text-fg">{Math.round(sm.p_win * 100)}%</b></span>
						<span>Empate: <b class="text-fg">{Math.round((sm.p_draw ?? 0) * 100)}%</b></span>
						<span>Gana {shortClub(sm.rival)}: <b class="text-fg">{Math.round((sm.p_loss ?? 0) * 100)}%</b></span>
					</div>
					<!-- Barra tripartita de probabilidades -->
					<div class="h-2 w-full flex rounded-full overflow-hidden bg-surface-2 border border-line">
						<div class="bg-emerald-500" style="width: {sm.p_win * 100}%"></div>
						<div class="bg-neutral-500" style="width: {(sm.p_draw ?? 0) * 100}%"></div>
						<div class="bg-rose-500" style="width: {(sm.p_loss ?? 0) * 100}%"></div>
					</div>
				</div>
			{/if}

			<!-- Jugadores de tu plantilla en este partido -->
			{#if playersInSelected.length}
				<div class="border-t border-line pt-2.5">
					<div class="text-[11px] font-bold text-fg mb-1.5 flex items-center gap-1.5">
						<span>Tus jugadores en este partido:</span>
						<span class="rounded bg-accent/20 px-1.5 py-0.2 text-[9px] text-accent font-bold">{playersInSelected.length}</span>
					</div>
					<div class="flex flex-wrap gap-1.5">
						{#each playersInSelected as p (p.player_id)}
							<a
								href="/jugador/{p.player_id}"
								class="chip bg-surface-2 border border-line text-xs hover:border-fg/40 transition-colors"
							>
								<span class="font-medium text-fg">{p.name}</span>
								<span class="text-muted text-[10px]">
									({POS[p.position_id]} · {p.isTeam ? sm.team : sm.rival})
								</span>
								{#if p.start_prob != null}
									<span class="text-[10px] font-bold {p.start_prob >= 0.8 ? 'text-up' : p.start_prob >= 0.5 ? 'text-warn' : 'text-down'}">
										· {Math.round(p.start_prob * 100)}% tit.
									</span>
								{/if}
							</a>
						{/each}
					</div>
				</div>
			{/if}

			<!-- Botón de cerrar -->
			<button
				type="button"
				onclick={() => (selectedMatch = null)}
				class="w-full rounded-xl bg-surface-2 hover:bg-surface-2/80 py-2 text-xs font-semibold text-fg transition-colors cursor-pointer border border-line"
			>
				Cerrar detalles
			</button>
		</div>
	</div>
{/if}
