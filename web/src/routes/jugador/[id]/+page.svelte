<script lang="ts">
	import { enhance } from '$app/forms';
	import Delta from '$lib/components/Delta.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Section from '$lib/components/Section.svelte';
	import SetPieces from '$lib/components/SetPieces.svelte';
	import ValueChart from '$lib/components/ValueChart.svelte';
	import WatchForm from '$lib/components/WatchForm.svelte';
	import {
		activityVerb,
		clauseState,
		dayText,
		formInfo,
		hierarchyInfo,
		injuryRisk,
		matchDay,
		matchResult,
		matchTime,
		money,
		num,
		POS,
		POS_LONG,
		relative,
		shortClub,
		signed
	} from '$lib/format';

	let { data, form: action } = $props();
	const c = $derived(data.card);
	const av = $derived(data.availability);
	const ss = $derived(data.seasonStats);

	const form = $derived(formInfo(ss?.form));
	const hier = $derived(hierarchyInfo(ss?.hierarchy));
	const risk = $derived(injuryRisk(av, c.status));

	const POS_BADGE: Record<number, string> = {
		1: 'bg-emerald-600 text-white',
		2: 'bg-blue-600 text-white',
		3: 'bg-amber-600 text-white',
		4: 'bg-rose-600 text-white',
		5: 'bg-purple-600 text-white'
	};

	const marks = $derived(
		data.history
			.filter((h) => [1, 31, 32, 33].includes(h.activity_type))
			.map((h) => ({
				day: h.happened_at.slice(0, 10),
				label: `${h.manager ?? ''} ${activityVerb(h.activity_type).split(' ')[0]}`.trim()
			}))
	);

	const firstDay = $derived(data.series.find((s) => s.value > 0)?.day ?? null);
	let range = $state<30 | 90 | 0>(0);
	const series = $derived(range ? data.series.slice(-range) : data.series);
	const max = $derived(Math.max(...data.series.map((s) => s.value)));
	const min = $derived(Math.min(...data.series.map((s) => s.value)));

	let showHistory = $state(false);
	const validSeries = $derived(data.series.filter((s) => s.value > 0));

	type DailyChange = {
		day: string;
		dateText: string;
		value: number;
		diff: number | null; // null: falta el día anterior, y no se deduce de otro
		pct: number | null;
	};

	// El cambio viene **guardado** (player_value_daily.change): solo existe si el día anterior es de
	// la misma fuente. Antes se restaba aquí contra el último dato que hubiera, saltando huecos y
	// mezclando FútbolFantasy con la API.
	const dailyChanges = $derived.by(() => {
		const list: DailyChange[] = [];
		for (let i = validSeries.length - 1; i >= 0; i--) {
			const cur = validSeries[i];
			const diff = cur.change ?? null;
			const antes = diff != null ? cur.value - diff : null;
			list.push({
				day: cur.day,
				dateText: new Date(cur.day + 'T12:00:00').toLocaleDateString('es-ES', { day: '2-digit', month: '2-digit' }),
				value: cur.value,
				diff,
				pct: diff != null && antes ? (diff / antes) * 100 : null
			});
		}
		return list;
	});

	// «Hoy» solo si de verdad son los valores de hoy (LaLiga los cambia a las 00:15).
	const esHoy = (day: string) => day === data.fresh?.values_expected;
	const todayChange = $derived(dailyChanges[0] ?? null);

	const maxItem = $derived.by(() => {
		if (!validSeries.length) return null;
		let maxEntry = validSeries[0];
		for (const s of validSeries) {
			if (s.value >= maxEntry.value) maxEntry = s;
		}
		return {
			value: maxEntry.value,
			date: new Date(maxEntry.day + 'T12:00:00').toLocaleDateString('es-ES', { day: 'numeric', month: 'short' })
		};
	});

	const minItem = $derived.by(() => {
		if (!validSeries.length) return null;
		let minEntry = validSeries[0];
		for (const s of validSeries) {
			if (s.value <= minEntry.value) minEntry = s;
		}
		return {
			value: minEntry.value,
			date: new Date(minEntry.day + 'T12:00:00').toLocaleDateString('es-ES', { day: 'numeric', month: 'short' })
		};
	});

	const STAT_LABELS: Record<string, string> = {
		mins_played: 'Minutos',
		goals: 'Goles',
		goal_assist: 'Asistencias',
		offtarget_att_assist: 'Asist. de tiro',
		pen_area_entries: 'Entradas al área',
		penalty_won: 'Penalti provocado',
		penalty_save: 'Penalti parado',
		saves: 'Paradas',
		effective_clearance: 'Despejes',
		penalty_failed: 'Penalti fallado',
		own_goals: 'Gol en propia',
		goals_conceded: 'Goles encajados',
		yellow_card: 'Amarilla',
		second_yellow_card: 'Segunda amarilla',
		red_card: 'Roja',
		total_scoring_att: 'Tiros',
		won_contest: 'Regates',
		ball_recovery: 'Recuperaciones',
		poss_lost_all: 'Pérdidas',
		penalty_conceded: 'Penalti cometido',
		marca_points: 'Puntos DAZN'
	};

	let openWeek = $state<number | null>(null);
	const st = $derived(data.owner ? clauseState(data.owner.clause_locked_until, data.owner.is_shielded) : null);
</script>

<svelte:head><title>lfm · {c.nickname ?? c.name}</title></svelte:head>

<PageHeader title={c.nickname ?? c.name} back="/plantilla">{POS_LONG[c.position_id]} · {c.club}</PageHeader>

<!-- 1. Banner de disponibilidad / estado físico + Acción comparar -->
<div class="mt-2 flex flex-wrap items-center justify-between gap-2 px-1">
	<div class="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-semibold {risk.statusCls}">
		<span class="inline-block h-2 w-2 rounded-full {risk.cls === 'text-up' ? 'bg-up' : risk.cls === 'text-warn' ? 'bg-warn' : 'bg-down'}"></span>
		{risk.statusText}
	</div>
	<div class="flex items-center gap-2">
		<a
			href="/comparar?p1={c.player_id}"
			class="bg-surface-2 hover:bg-surface-2/80 border border-line text-fg inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold transition-colors"
		>
			<span>Comparar</span>
		</a>
		{#if data.nextWeek}
			<span class="text-muted text-xs font-medium">Jornada {data.nextWeek} en camino</span>
		{/if}
	</div>
</div>

{#if data.owner?.is_me}
	<!-- Aquí no se decide si venderlo: lo decide el semáforo con el recomendador. Una segunda regla
	     escrita aquí (antes: «baja hoy y es suplente» = alerta de venta) contradecía a la otra. -->
	<a href="/plantilla?ver=ventas" class="border-line text-muted mt-2.5 flex items-center justify-between rounded-xl border px-3 py-2.5 text-xs">
		<span><span class="text-accent font-semibold">En tu plantilla</span>{#if c.value_1d != null && c.value !== c.value_1d}{' · '}{c.value > c.value_1d ? 'sube' : 'baja'} {signed(c.value - c.value_1d, 1)} hoy{/if}</span>
		<span class="text-accent">¿Venderlo? →</span>
	</a>
	<!-- «Es mi apuesta»: lo que el modelo no puede saber (que esperas que gane la titularidad) lo
	     decides tú, y el recomendador deja de mandarlo vender por una racha de mercado. -->
	<form method="POST" action="?/apuesta" use:enhance class="border-line mt-2 rounded-xl border px-3 py-2.5 text-xs">
		{#if data.thesis}
			{@const va = data.thesis.entry_value ? c.value / data.thesis.entry_value - 1 : null}
			<input type="hidden" name="on" value="0" />
			<div class="flex items-center justify-between gap-2">
				<div class="min-w-0">
					<div class="text-fg font-semibold">Tu apuesta{#if data.thesis.note}{' · '}<span class="text-muted font-normal">«{data.thesis.note}»</span>{/if}</div>
					<div class="text-muted mt-0.5">
						desde el {dayText(data.thesis.created_at)}{#if data.thesis.entry_value}{' a '}<span class="num">{money(data.thesis.entry_value, 1)}</span>{/if}{#if va != null}{' · '}<span class="num {va >= 0 ? 'text-up' : 'text-down'}">{va >= 0 ? '+' : '−'}{Math.abs(va * 100).toFixed(1).replace('.', ',')} %</span>{/if}
					</div>
				</div>
				<button class="text-muted shrink-0">Quitar</button>
			</div>
		{:else}
			<input type="hidden" name="on" value="1" />
			<div class="flex items-center gap-2">
				<input name="note" maxlength="120" placeholder="Por qué lo tienes (opcional)" class="bg-surface-2 text-fg placeholder:text-muted min-w-0 flex-1 rounded-lg px-2.5 py-1.5 outline-none" />
				<button class="bg-accent shrink-0 rounded-lg px-3 py-1.5 font-semibold text-black">Es mi apuesta</button>
			</div>
			<p class="text-muted mt-1.5">No se recomendará venderlo por una racha de mercado.</p>
		{/if}
		{#if action?.error}<p class="text-down mt-1.5">{action.error}</p>{/if}
	</form>
{:else}
	<WatchForm rule={data.watch} value={c.value} error={action?.watchError ?? null} />
{/if}

<!-- 2. Grid de 4 Indicadores Clave (Forma, Titularidad, Jerarquía, Riesgo les.) -->
<div class="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
	<!-- Forma -->
	<div class="bg-surface border-line flex flex-col items-center justify-between rounded-xl border p-3 text-center shadow-xs">
		<span class="text-muted text-[11px] font-bold tracking-wider uppercase">Forma</span>
		<div class="my-1.5 flex items-center gap-1">
			<span class="text-xl font-extrabold {form.iconCls}">{form.arrow}</span>
			{#if form.label !== '–'}
				<span class="text-sm font-bold {form.cls}">{form.label}</span>
			{/if}
		</div>
		<span class="text-muted text-[10px]">{form.label !== '–' ? 'Índice de forma' : 'Sin dato'}</span>
	</div>

	<!-- Titular J{nextWeek} -->
	<div class="bg-surface border-line flex flex-col items-center justify-between rounded-xl border p-3 text-center shadow-xs">
		<span class="text-muted text-[11px] font-bold tracking-wider uppercase">
			Titular estimado
		</span>
		<div class="border-line/80 num my-1.5 rounded-md border bg-[#0b0f15] px-3.5 py-0.5 text-base font-extrabold text-white shadow-inner">
			{av?.start_prob != null ? `${Math.round(av.start_prob * 100)}%` : '–'}
		</div>
		<span class="text-muted text-[10px]">{av?.start_prob != null ? 'Próximo partido · no confirmado' : 'Sin previsión vigente'}</span>
		{#if av?.source_url}<a href={av.source_url} target="_blank" rel="noreferrer" class="text-accent mt-1 text-[10px] underline">FútbolFantasy{av.fetched_at ? ` · ${relative(av.fetched_at)}` : ''}</a>{/if}
	</div>

	<!-- Jerarquía -->
	<div class="bg-surface flex flex-col items-center justify-between rounded-xl border p-3 text-center shadow-xs {hier.badgeCls}">
		<span class="text-[11px] font-bold tracking-wider uppercase opacity-80">Jerarquía</span>
		<div class="my-1.5 flex items-center gap-1.5 text-sm font-extrabold {hier.cls}">
						<span>{hier.label}</span>
		</div>
		<span class="text-[10px] opacity-75">{hier.subtitle}</span>
	</div>

	<!-- Riesgo lesión -->
	<div class="bg-surface border-line flex flex-col items-center justify-between rounded-xl border p-3 text-center shadow-xs">
		<span class="text-muted text-[11px] font-bold tracking-wider uppercase">Riesgo les.</span>
		<div class="my-1.5 flex items-center gap-1 text-sm font-extrabold {risk.cls}">
			<span class="size-2 rounded-full {risk.cls === 'text-up' ? 'bg-up' : risk.cls === 'text-warn' ? 'bg-warn' : 'bg-down'}"></span>
			<span>{risk.label}</span>
		</div>
		<span class="text-muted text-[10px]">{risk.statusText}</span>
	</div>
</div>

<!-- 3. Showcase: Tarjeta FUT estilo cromo de fútbol + Datos rápidos -->
<div class="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
	<!-- Tarjeta estilo FIFA / FUT Panini -->
	<div class="relative overflow-hidden rounded-2xl border-2 border-amber-500/40 bg-gradient-to-b from-[#221c12] via-[#151310] to-[#0c0d10] p-4 text-center shadow-xl shadow-amber-950/20 sm:col-span-1">
		<!-- Badges superiores -->
		<div class="flex items-center justify-between">
			<span class="rounded px-2 py-0.5 text-[11px] font-black tracking-wider uppercase {POS_BADGE[c.position_id]} shadow-xs">
				{POS[c.position_id]}
			</span>
			{#if c.badge_url}
				<img src={c.badge_url} alt={c.club} class="h-8 w-8 object-contain drop-shadow-md" />
			{/if}
		</div>

		<!-- Foto del jugador -->
		<div class="relative my-2 flex h-36 items-center justify-center">
			{#if c.image_url}
				<img
					src={c.image_url}
					alt={c.nickname ?? c.name}
					class="max-h-36 max-w-full object-contain drop-shadow-[0_8px_16px_rgba(0,0,0,0.85)]"
				/>
			{:else}
				<div class="bg-surface-2/60 text-muted flex h-28 w-28 items-center justify-center rounded-full text-3xl font-bold">
					{c.name.slice(0, 2).toUpperCase()}
				</div>
			{/if}
		</div>

		<!-- Nombre & Club -->
		<div class="truncate text-base font-black tracking-widest text-amber-100 uppercase">
			{c.nickname ?? c.name}
		</div>
		<div class="text-muted text-xs font-medium">
			{c.club}
		</div>

		<!-- Cinta de estadísticas de temporada -->
		<div class="border-line/70 mt-3 grid grid-cols-3 divide-x divide-line/60 border-t pt-2 text-[11px]">
			<div>
				<div class="num font-bold text-fg">{ss?.games ?? (c.points_total ? data.weeks.length : 0)}</div>
				<div class="text-muted text-[10px]">Partidos</div>
			</div>
			<div>
				<div class="num font-bold text-fg">{ss?.minutes != null ? `${ss.minutes}'` : '–'}</div>
				<div class="text-muted text-[10px]">Minutos</div>
			</div>
			<div>
				{#if c.position_id === 1}
					<div class="num font-bold text-fg">{c.points_total}</div>
					<div class="text-muted text-[10px]">Puntos</div>
				{:else}
					<div class="num font-bold text-fg">{ss?.goals ?? 0}G · {ss?.assists ?? 0}A</div>
					<div class="text-muted text-[10px]">Goles / Asist.</div>
				{/if}
			</div>
		</div>
	</div>

	<!-- Resumen deportivo & económico -->
	<div class="card flex flex-col justify-between p-4 sm:col-span-2">
		<div>
			<div class="text-muted flex items-center justify-between text-xs">
				<span>Valor de mercado actual</span>
				<span class="num font-semibold text-fg">{c.points_total} pts totales · media {num(c.average_points, 1)}</span>
			</div>
			<div class="mt-1 flex flex-wrap items-baseline gap-2.5">
				<span class="num text-[32px] font-medium leading-none tracking-tighter text-fg">
					{money(c.value, 2)}
				</span>
				{#if todayChange && todayChange.diff != null && todayChange.diff !== 0}
					<span
						title="{todayChange.diff > 0 ? '+' : ''}{todayChange.diff.toLocaleString('es-ES')} € {esHoy(todayChange.day) ? 'hoy' : `el ${todayChange.dateText}`}"
						class="num inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-bold {todayChange.diff > 0 ? 'bg-up/15 text-up border border-up/30' : 'bg-down/15 text-down border border-down/30'}"
					>
						<span>{todayChange.diff > 0 ? '▲' : '▼'}</span>
						<span>{signed(todayChange.diff, 1)} {esHoy(todayChange.day) ? 'hoy' : `el ${todayChange.dateText}`}</span>
						{#if todayChange.pct != null}
							<span class="opacity-80">({todayChange.pct > 0 ? '+' : ''}{todayChange.pct.toLocaleString('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%)</span>
						{/if}
					</span>
				{/if}
			</div>
			<div class="mt-2 flex flex-wrap gap-x-3.5 gap-y-1 text-xs">
				<span><span class="text-muted">1 d</span> <Delta now={c.value} before={c.value_1d} showPct={false} size="text-xs" /></span>
				<span><span class="text-muted">7 d</span> <Delta now={c.value} before={c.value_7d} showPct={false} size="text-xs" /></span>
				<span><span class="text-muted">30 d</span> <Delta now={c.value} before={c.value_30d} showPct={false} size="text-xs" /></span>
			</div>
		</div>

		<!-- Mini tabla de desglose de temporada -->
		<div class="border-line/70 bg-surface-2/30 mt-3 grid grid-cols-2 gap-2 rounded-xl border p-2.5 text-xs sm:grid-cols-4">
			<div>
				<span class="text-muted text-[10px] block">Titularidades</span>
				<span class="num font-semibold text-fg">
					{#if ss?.games != null}
						{ss.games - (ss.games_as_sub ?? 0)} / {ss.games}
					{:else}
						–
					{/if}
				</span>
			</div>
			<div>
				<span class="text-muted text-[10px] block">Entró suplente</span>
				<span class="num font-semibold text-fg">{ss?.games_as_sub ?? 0}</span>
			</div>
			<div>
				<span class="text-muted text-[10px] block">Sustituido</span>
				<span class="num font-semibold text-fg">{ss?.games_subbed_off ?? 0}</span>
			</div>
			<div>
				<span class="text-muted text-[10px] block">Tarjetas</span>
				<span class="num font-semibold text-fg"><span class="inline-block h-2.5 w-[7px] rounded-[1.5px] bg-warn align-[-1px]"></span> {ss?.yellows ?? 0} · <span class="inline-block h-2.5 w-[7px] rounded-[1.5px] bg-down align-[-1px]"></span> {ss?.reds ?? 0}</span>
			</div>
		</div>

		{#if data.owner}
			<div class="border-line/70 mt-3 flex items-center justify-between border-t pt-2.5 text-xs">
				<div>
					<span class="text-muted">Propietario en tu liga:</span>
					<a href="/liga/{data.owner.team_id}" class="ml-1 font-semibold {data.owner.is_me ? 'text-accent' : 'text-fg'}">
						{data.owner.is_me ? 'Tú' : data.owner.manager_name}
					</a>
				</div>
				<div class="text-right">
					<span class="text-muted">Cláusula:</span>
					<span class="num ml-1 font-semibold">{money(data.owner.buyout_clause)}</span>
					<span class="ml-1 text-[11px] {st?.cls}">({st?.label})</span>
				</div>
			</div>
		{:else}
			<div class="text-muted border-line/70 mt-3 border-t pt-2 text-xs">
				Libre en tu liga.
			</div>
		{/if}
	</div>
</div>

<!-- 4. Sección: Últimos 5 partidos -->
{#if data.recentMatches && data.recentMatches.length > 0}
	<div class="mt-4">
		<div class="mb-2 flex items-center gap-1.5 px-1">
			<h2 class="text-sm font-semibold tracking-tight text-fg">Últimos partidos</h2>
		</div>
		<div class="flex gap-2 overflow-x-auto pb-1 scrollbar-none">
			{#each data.recentMatches as m (m.match_id)}
				{@const res = matchResult(m.local_score, m.visitor_score, m.is_home)}
				{@const oppName = m.is_home ? m.visitor_name : m.local_name}
				{@const oppBadge = m.is_home ? m.visitor_badge : m.local_badge}
				<div class="bg-surface rounded-xl border p-2.5 flex flex-col justify-between min-w-[130px] flex-1 shrink-0 text-xs shadow-xs {res.badgeCls.includes('text-up') ? 'border-up/40' : res.badgeCls.includes('text-down') ? 'border-down/40' : 'border-line'}">
					<!-- Fecha y Jornada -->
					<div class="flex justify-between items-center text-[11px] text-muted">
						<span>{matchDay(m.match_date)}</span>
						<span class="font-bold">J{m.week}</span>
					</div>

					<!-- Resultado & Escudo rival -->
					<div class="my-2 flex items-center justify-between gap-1.5">
						<div class="flex items-center gap-1.5">
							<span class="inline-flex items-center justify-center w-5 h-5 rounded text-[10px] font-black border {res.badgeCls}">
								{res.code}
							</span>
							<span class="num font-bold text-sm tracking-tight text-fg">
								{m.local_score ?? '–'} - {m.visitor_score ?? '–'}
							</span>
						</div>
						{#if oppBadge}
							<img src={oppBadge} alt={oppName} class="h-6 w-6 object-contain" />
						{/if}
					</div>

					<!-- Rival & Puntos / Minutos -->
					<div class="border-t border-line/60 pt-1.5 mt-0.5 flex justify-between items-center text-[10px] text-muted">
						<span class="truncate"><strong class="text-[9px] font-bold {m.is_home ? 'text-muted' : 'text-accent'}">{m.is_home ? '(C)' : '(F)'}</strong> {shortClub(oppName)}</span>
						{#if m.total_points != null}
							<span class="num font-bold text-fg">{m.total_points} pts</span>
						{:else if m.mins_played}
							<span class="num">{m.mins_played}'</span>
						{/if}
					</div>
				</div>
			{/each}
		</div>
	</div>
{/if}

<!-- 5. Sección: Próximos 5 partidos -->
{#if data.upcomingMatches && data.upcomingMatches.length > 0}
	<div class="mt-4">
		<div class="mb-2 flex items-center gap-1.5 px-1">
			<h2 class="text-sm font-semibold tracking-tight text-fg">Próximos partidos</h2>
		</div>
		<div class="flex gap-2 overflow-x-auto pb-1 scrollbar-none">
			{#each data.upcomingMatches as m (m.match_id)}
				{@const oppName = m.is_home ? m.visitor_name : m.local_name}
				{@const oppBadge = m.is_home ? m.visitor_badge : m.local_badge}
				<div class="bg-surface border-line rounded-xl border p-2.5 flex flex-col justify-between min-w-[130px] flex-1 shrink-0 text-xs shadow-xs">
					<!-- Fecha y Jornada -->
					<div class="flex justify-between items-center text-[11px] text-muted">
						<span>{matchDay(m.match_date)}</span>
						<span class="font-bold">J{m.week}</span>
					</div>

					<!-- Casa/Fuera & Horario & Escudo rival -->
					<div class="my-2 flex items-center justify-between gap-1.5">
						<div class="flex items-center gap-1">
							<span class="text-muted text-[10px] font-semibold">{m.is_home ? 'CASA' : 'FUERA'}</span>
							<span class="num font-semibold text-xs text-fg">{matchTime(m.match_date)}</span>
						</div>
						{#if oppBadge}
							<img src={oppBadge} alt={oppName} class="h-6 w-6 object-contain" />
						{/if}
					</div>

					<!-- Rival & Probabilidad de victoria -->
					<div class="border-t border-line/60 pt-1.5 mt-0.5 flex justify-between items-center text-[10px] text-muted">
						<span class="truncate"><strong class="text-[9px] font-bold {m.is_home ? 'text-muted' : 'text-accent'}">{m.is_home ? '(C)' : '(F)'}</strong> {shortClub(oppName)}</span>
						{#if (m.is_home ? m.p_local : m.p_visitor) != null}
							{@const myProb = (m.is_home ? m.p_local : m.p_visitor)!}
							<span class="num font-bold {myProb >= 0.45 ? 'text-up' : myProb <= 0.25 ? 'text-down' : 'text-warn'}">
								{Math.round(myProb * 100)}%
							</span>
						{/if}
					</div>
				</div>
			{/each}
		</div>
	</div>
{/if}

<!-- 6. En el mercado (si procede) -->
{#if data.onSale}
	<div class="card mt-4 p-4">
		<div class="text-muted text-xs">En el mercado de tu liga</div>
		<div class="flex items-baseline justify-between">
			<span>{data.onSale.seller ? `Vende ${data.onSale.seller}` : 'Lo vende el sistema'}{#if data.onSale.num_bids} · {data.onSale.num_bids} pujas{/if}</span>
			<span class="num font-semibold">{money(data.onSale.sale_price)}</span>
		</div>
		<div class="text-muted text-xs">Cierra {relative(data.onSale.expires_at)}</div>
	</div>
{/if}

<!-- 7. Gráfico de valor de mercado e histórico diario -->
<Section title="Evolución del valor">
	{#snippet aside()}
		<div class="border-line bg-surface-2/80 inline-flex rounded-lg border p-0.5">
			{#each [[30, '30 días'], [90, '90 días'], [0, 'Todo']] as [k, label] (k)}
				<button
					class="rounded-md px-2.5 py-1 text-xs font-medium transition-colors {range === k ? 'bg-surface text-fg shadow-xs font-bold' : 'text-muted hover:text-fg'}"
					onclick={() => (range = k as typeof range)}
				>
					{label}
				</button>
			{/each}
		</div>
	{/snippet}

	<!-- Header de estadísticas de valor (exacto como la referencia) -->
	<div class="mb-3 rounded-xl border border-line bg-surface-2/30 p-3">
		<div class="flex flex-wrap items-baseline justify-between gap-2">
			<div class="flex flex-wrap items-baseline gap-2">
				<span class="text-xs font-semibold text-muted">Valor act:</span>
				<span class="num text-base font-extrabold text-fg">{c.value.toLocaleString('es-ES')} €</span>
				{#if todayChange && todayChange.diff != null && todayChange.diff !== 0}
					<span class="num inline-flex items-center gap-0.5 text-xs font-bold {todayChange.diff > 0 ? 'text-up' : 'text-down'}">
						({todayChange.diff > 0 ? '+' : ''}{todayChange.diff.toLocaleString('es-ES')} €)
						<span class="text-[10px]">{todayChange.diff > 0 ? '▲' : '▼'}</span>
					</span>
				{/if}
			</div>
			<div class="text-muted flex flex-wrap gap-x-4 gap-y-1 text-xs">
				{#if maxItem}
					<span>Valor máx: <strong class="num font-semibold text-fg">{maxItem.value.toLocaleString('es-ES')} €</strong> ({maxItem.date})</span>
				{/if}
				{#if minItem}
					<span>Valor mín: <strong class="num font-semibold text-fg">{minItem.value.toLocaleString('es-ES')} €</strong> ({minItem.date})</span>
				{/if}
			</div>
		</div>
	</div>

	<ValueChart {series} {marks} />

	<!-- Botón desplegable para mostrar/ocultar histórico (como en FútbolFantasy) -->
	<button
		onclick={() => (showHistory = !showHistory)}
		aria-expanded={showHistory}
		class="border-line active:bg-surface-2 mt-3 flex w-full items-center justify-center gap-1.5 rounded-xl border bg-[#0b0f15] py-2.5 px-4 text-xs font-bold text-fg shadow-xs transition-colors hover:bg-[#121822]"
	>
		<span>{showHistory ? 'Ocultar histórico' : 'Ver histórico diario'}</span>
		<span class="text-xs">{showHistory ? '▴' : '▾'}</span>
	</button>

	<!-- Tabla de histórico diario de subidas y bajadas -->
	{#if showHistory}
		<div class="border-line bg-surface mt-2 overflow-hidden rounded-xl border shadow-inner">
			<div class="max-h-72 overflow-y-auto scrollbar-thin">
				<table class="w-full border-collapse text-left text-xs">
					<thead class="border-line bg-surface-2/95 text-muted sticky top-0 border-b text-[11px] font-bold tracking-wider uppercase backdrop-blur-xs">
						<tr>
							<th class="py-2.5 px-3">Fecha</th>
							<th class="py-2.5 px-3 text-center">Subida / Bajada</th>
							<th class="py-2.5 px-3 text-right">Valor</th>
						</tr>
					</thead>
					<tbody class="divide-line/60 divide-y">
						{#each dailyChanges as d (d.day)}
							<tr class="hover:bg-surface-2/40 transition-colors">
								<td class="num text-muted py-2 px-3 font-medium">{d.dateText}</td>
								<td class="num py-2 px-3 text-center font-semibold {d.diff == null ? 'text-muted' : d.diff > 0 ? 'text-up' : d.diff < 0 ? 'text-down' : 'text-muted'}">
									{#if d.diff == null}
										<span class="font-normal">sin dato del día anterior</span>
									{:else}
										{d.diff > 0 ? '+' : ''}{d.diff.toLocaleString('es-ES')} €
										{#if d.pct != null}
											<span class="ml-1 text-[10px] font-normal opacity-85">({d.pct > 0 ? '+' : ''}{d.pct.toLocaleString('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%)</span>
										{/if}
									{/if}
								</td>
								<td class="num text-fg py-2 px-3 text-right font-semibold">
									{d.value.toLocaleString('es-ES')} €
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
	{/if}
</Section>

<!-- 8. Balón parado -->
{#if data.setPieces}
	<Section title="Balón parado" flush>
		<SetPieces sp={data.setPieces} club={data.card.club} />
	</Section>
{/if}

<!-- 9. Puntos por jornada -->
{#if data.weeks.length}
	<Section title="Puntos por jornada" flush>
		<div class="divide-line divide-y">
			{#each data.weeks as w (w.week)}
				<button class="flex w-full items-center justify-between px-3 py-2 text-left" onclick={() => (openWeek = openWeek === w.week ? null : w.week)} disabled={!w.stats}>
					<span class="text-muted text-sm">Jornada {w.week}</span>
					<span class="num font-semibold {(w.total_points ?? 0) >= 8 ? 'text-up' : (w.total_points ?? 0) < 2 ? 'text-down' : ''}">
						{w.total_points ?? '–'}{#if w.stats}<span class="text-muted ml-2 text-xs">{openWeek === w.week ? '▴' : '▾'}</span>{/if}
					</span>
				</button>
				{#if openWeek === w.week && w.stats}
					<div class="bg-surface-2/50 grid grid-cols-2 gap-x-4 px-3 py-2 text-xs">
						{#each Object.entries(w.stats).filter(([, v]) => v[1] !== 0 || v[0] !== 0) as [k, v] (k)}
							<div class="flex justify-between py-0.5">
								<span class="text-muted">{STAT_LABELS[k] ?? k} <span class="num">({v[0]})</span></span>
								<span class="num {v[1] > 0 ? 'text-up' : v[1] < 0 ? 'text-down' : 'text-muted'}">{v[1] > 0 ? '+' : ''}{v[1]}</span>
							</div>
						{/each}
					</div>
				{/if}
			{/each}
		</div>
	</Section>
{/if}

<!-- 10. Historial en tu liga -->
{#if data.history.length}
	<Section title="Historial en tu liga" flush>
		<ul class="divide-line divide-y text-sm">
			{#each data.history as h, i (i)}
				<li class="flex items-center gap-2 px-3 py-2">
					<span class="text-muted w-16 shrink-0 text-xs">{dayText(h.happened_at)}</span>
					<span class="flex-1"><span class="font-medium">{h.manager ?? "?"}</span> {activityVerb(h.activity_type)}{#if h.manager2}<span class="text-muted">&nbsp;(de {h.manager2})</span>{/if}</span>
					{#if h.amount}<span class="num">{money(h.amount)}</span>{/if}
				</li>
			{/each}
		</ul>
	</Section>
{/if}
