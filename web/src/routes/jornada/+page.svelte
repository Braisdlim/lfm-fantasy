<script lang="ts">
	import { page } from '$app/state';
	import FDRGrid from '$lib/components/FDRGrid.svelte';
	import OddsBar from '$lib/components/OddsBar.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Section from '$lib/components/Section.svelte';
	import { POS, fixed, shortClub, timeText } from '$lib/format';
	import type { Match, SquadByTeam } from '$lib/server/queries';

	let { data } = $props();
	// La subvista va en la URL y no en un estado suelto: así se puede enlazar directamente a
	// «Para fichar» desde otra pantalla, y el botón de atrás del móvil hace lo que se espera.
	type Vista = 'tuyos' | 'fichar' | 'proximas';
	const VISTAS: Vista[] = ['tuyos', 'fichar', 'proximas'];
	const tab = $derived((VISTAS.find((v) => v === page.url.searchParams.get('ver')) ?? 'tuyos') as Vista);

	const pct = (x: number | null | undefined) => (x == null ? '–' : `${Math.round(x * 100)} %`);

	// Los jugadores que tienes tú, por club. Es lo que convierte un partido cualquiera en "tu" partido.
	const mios = $derived.by(() => {
		const m = new Map<string, SquadByTeam[]>();
		for (const p of data.owned.filter((p) => p.mine)) {
			if (!m.has(p.team_id)) m.set(p.team_id, []);
			m.get(p.team_id)!.push(p);
		}
		return m;
	});

	// Los adelantados vienen con resultado: cuentan para la rejilla de próximas jornadas, pero no
	// para «qué va a pasar esta jornada», que es de lo que hablan las otras dos vistas.
	const porJugar = $derived(data.fixtures.filter((f) => f.local_score == null));
	const jornada = $derived(porJugar.length ? porJugar[0].week : null);
	const deLaJornada = $derived(porJugar.filter((f) => f.week === jornada));
	const conLosTuyos = $derived(deLaJornada.filter((f) => mios.has(f.local_id) || mios.has(f.visitor_id)));
	const sinLosTuyos = $derived(deLaJornada.filter((f) => !mios.has(f.local_id) && !mios.has(f.visitor_id)));

	// Con cuántos partidos se ha estimado el modelo. Con pocos, conviene decirlo una vez y no
	// repetir un aviso en cada tarjeta.
	const jugados = $derived(porJugar.length ? Math.min(...porJugar.map((f) => f.played ?? 0)) : 0);

	/** Cada equipo con su partido visto desde su lado: lo que se espera que marque y que encaje. */
	type Lado = { team_id: string; team: string; rival: string; casa: boolean; xg: number; cs: number; week: number; marcador: string | null };
	const lados = $derived.by(() => {
		const out: Lado[] = [];
		for (const f of deLaJornada) {
			if (f.xg_local == null || f.xg_visitor == null) continue;
			out.push({ team_id: f.local_id, team: f.local, rival: f.visitor, casa: true, xg: f.xg_local, cs: f.cs_local ?? 0, week: f.week, marcador: null });
			out.push({ team_id: f.visitor_id, team: f.visitor, rival: f.local, casa: false, xg: f.xg_visitor, cs: f.cs_visitor ?? 0, week: f.week, marcador: null });
		}
		return out;
	});
	const paraAtacar = $derived([...lados].sort((a, b) => b.xg - a.xg).slice(0, 6));
	const paraDefender = $derived([...lados].sort((a, b) => b.cs - a.cs).slice(0, 6));
</script>

<svelte:head><title>lfm · Jornada</title></svelte:head>

<PageHeader title={jornada ? `Jornada ${jornada}` : 'Jornada'}>
	{#if jugados}<span class="text-muted text-xs">estimado con {jugados} partidos</span>{/if}
</PageHeader>

<div class="bg-surface-2 mt-3 flex rounded-xl p-1 text-[11px]">
	{#each [['tuyos', `Tus partidos · ${conLosTuyos.length}`], ['fichar', 'Para fichar'], ['proximas', 'Calendario FDR']] as [k, label] (k)}
		<a href="/jornada?ver={k}" data-sveltekit-replacestate class="flex-1 rounded-lg py-1.5 text-center {tab === k ? 'bg-surface font-semibold' : 'text-muted'}">{label}</a>
	{/each}
</div>

{#snippet partido(f: Match)}
	{@const suyos = [...(mios.get(f.local_id) ?? []), ...(mios.get(f.visitor_id) ?? [])]}
	<div class="border-line border-b px-1 py-3 last:border-0">
		<div class="text-muted text-[11px]">{timeText(f.date)}</div>

		{#each [[f.local, f.xg_local, f.cs_local, true], [f.visitor, f.xg_visitor, f.cs_visitor, false]] as [nombre, xg, cs] (nombre)}
			<div class="mt-1.5 flex items-baseline gap-2">
				<span class="min-w-0 flex-1 truncate text-sm font-medium">{nombre}</span>
				<!-- La mono, solo en la cifra: «marca» y «goles» en monoespaciada se leen peor. -->
				<span class="text-muted shrink-0 text-xs">
					marca <span class="num text-fg font-semibold">{fixed(xg as number, 1)}</span> goles
				</span>
				<span class="text-muted w-24 shrink-0 text-right text-xs">
					a cero <span class="num text-fg font-semibold">{pct(cs as number)}</span>
				</span>
			</div>
		{/each}

		{#if f.p_local != null}
			<div class="mt-2.5"><OddsBar local={f.p_local} draw={f.p_draw ?? 0} visitor={f.p_visitor ?? 0} /></div>
			<p class="text-muted mt-1.5 text-xs leading-snug">
				Gana el <span class="text-fg">{f.local}</span> el {pct(f.p_local)} de las veces, empatan el {pct(f.p_draw)} y gana el
				<span class="text-fg">{f.visitor}</span> el {pct(f.p_visitor)}.
			</p>
		{:else}
			<p class="text-muted mt-2 text-xs">Sin pronóstico todavía: faltan resultados para estimarlo.</p>
		{/if}

		{#if suyos.length}
			<div class="mt-2 flex flex-wrap gap-1">
				{#each suyos as p (p.player_id)}
					<a href="/jugador/{p.player_id}" class="chip bg-surface-2 text-xs">
						{p.name}
						<span class="text-muted">{POS[p.position_id]} · {p.start_prob != null ? `${Math.round(p.start_prob * 100)} % titular` : 'sin dato'}</span>
					</a>
				{/each}
			</div>
		{/if}
	</div>
{/snippet}

{#if tab === 'tuyos'}
	{#if conLosTuyos.length}
		<Section title="Donde te juegas algo" flush bare>
			{#snippet aside()}{conLosTuyos.length} de los {deLaJornada.length} partidos{/snippet}
			{#each conLosTuyos as f (f.match_id)}{@render partido(f)}{/each}
		</Section>
	{/if}
	{#if sinLosTuyos.length}
		<Section title="El resto de la jornada" flush bare>
			{#each sinLosTuyos as f (f.match_id)}{@render partido(f)}{/each}
		</Section>
	{/if}

{:else if tab === 'fichar'}
	<Section title="Para fichar delanteros" flush bare>
		{#snippet aside()}los que más marcan{/snippet}
		{#each paraAtacar as l (l.team_id)}
			<div class="border-line flex items-baseline gap-2 border-b px-1 py-2.5 last:border-0">
				<div class="min-w-0 flex-1">
					<div class="truncate text-sm font-medium">{l.team}</div>
					<div class="text-muted truncate text-xs">{l.casa ? 'en casa contra' : 'fuera contra'} {l.rival}</div>
				</div>
				<div class="shrink-0 text-right">
					<div class="num text-base font-semibold">{fixed(l.xg, 1)}</div>
					<div class="text-muted text-[11px]">goles esperados</div>
				</div>
			</div>
		{/each}
	</Section>

	<Section title="Para fichar defensas y portero" flush bare>
		{#snippet aside()}los que menos encajan{/snippet}
		{#each paraDefender as l (l.team_id)}
			<div class="border-line flex items-baseline gap-2 border-b px-1 py-2.5 last:border-0">
				<div class="min-w-0 flex-1">
					<div class="truncate text-sm font-medium">{l.team}</div>
					<div class="text-muted truncate text-xs">{l.casa ? 'en casa contra' : 'fuera contra'} {l.rival}</div>
				</div>
				<div class="shrink-0 text-right">
					<div class="num text-base font-semibold">{pct(l.cs)}</div>
					<div class="text-muted text-[11px]">deja la portería a cero</div>
				</div>
			</div>
		{/each}
	</Section>

{:else}
	<div class="mt-2">
		<FDRGrid fixtures={data.fixtures} owned={data.owned} />
	</div>
{/if}
