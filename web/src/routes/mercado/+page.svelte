<script lang="ts">
	import { page } from '$app/state';
	import { replaceState } from '$app/navigation';
	import Accuracy from '$lib/components/Accuracy.svelte';
	import Countdown from '$lib/components/Countdown.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import PlayerRow from '$lib/components/PlayerRow.svelte';
	import RecCard from '$lib/components/RecCard.svelte';
	import Section from '$lib/components/Section.svelte';
	import ValueNote from '$lib/components/ValueNote.svelte';
	import { dayText, money, moveText, num, pctText, playerTrend, POS, POS_BADGE, POS_PLURAL, priceVerdict, relative, shortClub, signed } from '$lib/format';
	let { data } = $props();
	// La pestaña va en la URL: se puede enlazar «Mercado · Chollos» desde otra pantalla y el botón
	// de atrás del móvil hace lo que se espera.
	type Tab = 'laliga' | 'precio' | 'recomendado' | 'chollos' | 'acierto' | 'liga' | 'managers' | 'mias' | 'radar';
	const TABS: Tab[] = ['laliga', 'precio', 'recomendado', 'chollos', 'acierto', 'liga', 'managers', 'mias', 'radar'];
	const tab = $derived.by(() => {
		const param = page.state.marketTab ?? page.url.searchParams.get('ver');
		if (param === 'radar') return 'laliga';
		return param && TABS.includes(param as Tab) ? param as Tab : 'recomendado';
	});

	function setTab(k: Tab) {
		const u = new URL(page.url);
		u.searchParams.set('ver', k);
		replaceState(u, { ...page.state, marketTab: k });
	}
	// Filtro por posición: es el atajo que llega desde Plantilla · Once, donde el hueco más débil
	// tiene un puesto concreto y no sirve de nada abrir la lista entera.
	const pos = $derived(Number(page.url.searchParams.get('pos')) || 0);
	const dePosicion = <T extends { position_id: number | null }>(l: T[]) => (pos ? l.filter((x) => x.position_id === pos) : l);
	const pujar = $derived(dePosicion(data.recs.filter((r) => r.verdict === 'pujar')));
	const sinSaldo = $derived(dePosicion(data.recs.filter((r) => r.kind === 'buy' && r.verdict === 'sin_saldo')));
	const recByPlayer = $derived(new Map(data.recs.filter((r) => r.kind === 'buy').map((r) => [r.player_id, r])));
	const vender = $derived(data.recs.filter((r) => r.kind === 'sell'));
	const ventas = $derived(vender.filter((r) => r.verdict === 'vender'));
	const mantener = $derived(vender.filter((r) => r.verdict !== 'vender'));
	const missingEleven = $derived(data.recs.find((r) => r.missing_eleven?.length)?.missing_eleven ?? []);
	// Rebote: vienen bajando pero con un hecho que, medido, les dio la vuelta. Van aparte aunque no
	// compense pujar hoy, para que se vean antes de que el valor reaccione.
	const rebote = $derived(dePosicion(data.recs.filter((r) => r.kind === 'buy' && r.rebound && !['pujar', 'sin_saldo'].includes(r.verdict))));
	const descartados = $derived(
		dePosicion(data.recs.filter((r) => r.kind === 'buy' && !['pujar', 'sin_saldo'].includes(r.verdict) && !r.rebound))
	);
	let verDescartados = $state(false);
	let sort = $state<'subida' | 'precio' | 'valor' | 'semana'>('subida');
	const cash = $derived(data.team?.team_money ?? 0);
	const plannedBids = $derived(data.recs.filter((r) => r.verdict === 'pujar').reduce((sum, r) => sum + (r.bid_to_win ?? 0), 0));
	const availableOffers = $derived(data.listings.reduce((sum, p) => sum + (p.offer_money ?? 0), 0));

	// Filtros de Por Precio
	type PriceFilter = 'all' | 'low' | 'mid' | 'high' | 'premium';
	let pickTier = $state<PriceFilter>('all');
	let pickPos = $state<number>(0);
	$effect(() => {
		if (pos) pickPos = pos;
	});
	let pickSort = $state<'score' | 'puntos' | 'precio' | 'subida'>('score');

	const pickList = $derived.by(() => {
		let list = data.picks ?? [];
		if (pickTier !== 'all') {
			list = list.filter((p) => p.tier === pickTier);
		}
		if (pickPos > 0) {
			list = list.filter((p) => p.position_id === pickPos);
		}
		const sorted = [...list];
		if (pickSort === 'puntos') {
			sorted.sort((a, b) => (b.average_points ?? 0) - (a.average_points ?? 0));
		} else if (pickSort === 'precio') {
			sorted.sort((a, b) => a.value - b.value);
		} else if (pickSort === 'subida') {
			sorted.sort(
				(a, b) =>
					(b.value_1d != null ? b.value - b.value_1d : 0) - (a.value_1d != null ? a.value - a.value_1d : 0)
			);
		} else {
			sorted.sort((a, b) => b.score - a.score);
		}
		return sorted;
	});

	// Filtros de LaLiga Hoy
	let moverDir = $state<'up' | 'down'>('up');
	let moverMetric = $state<'eur' | 'pct'>('eur');
	let moverPos = $state<number>(0);

	const moverList = $derived.by(() => {
		const raw =
			moverDir === 'up'
				? moverMetric === 'eur'
					? data.radar.up
					: data.radar.up_pct
				: moverMetric === 'eur'
					? data.radar.down
					: data.radar.down_pct;
		return moverPos ? raw.filter((p) => p.position_id === moverPos) : raw;
	});

	const POS_BORDER: Record<number, string> = {
		1: 'border-emerald-500/80',
		2: 'border-blue-500/80',
		3: 'border-amber-500/80',
		4: 'border-rose-500/80',
		5: 'border-purple-500/80'
	};

	// Cuándo se calcularon estas recomendaciones. Si el job falla, la app sigue enseñando las de la
	// última pasada buena y no había forma de notarlo: el 15 de septiembre estuvieron seis horas
	// mostrando las de las 17:05 mientras el mercado ya había rotado.
	const calculadoEn = $derived(data.recs[0]?.created_at ?? null);
	const desfasadas = $derived(
		!!(calculadoEn && data.fresh?.market && new Date(data.fresh.market) > new Date(calculadoEn))
	);
	const calculadas = $derived(
		!calculadoEn
			? `con tu saldo de ${money(cash)}`
			: desfasadas
				? `⚠ calculadas ${relative(calculadoEn)}, antes del último mercado`
				: `calculadas ${relative(calculadoEn)}`
	);

	function ordered(list: typeof data.league) {
		const key = (m: (typeof list)[number]) =>
			sort === 'precio'
				? -m.sale_price
				: sort === 'valor'
					? m.value
					: sort === 'semana'
						? (m.value_7d != null ? m.value - m.value_7d : -Infinity)
						: m.value_1d != null ? m.value - m.value_1d : -Infinity;
		return [...list].sort((a, b) => key(b) - key(a));
	}
</script>

<svelte:head><title>lfm · Mercado</title></svelte:head>

<PageHeader title="Mercado" fresh={data.fresh} shows="mercado" />
<p class="text-muted mb-4 text-sm">Qué comprar, cuánto pagar y cuándo salir.</p>
<a href="/planificar" class="border-line text-accent mb-3 flex min-h-11 items-center justify-between border-y px-1 text-sm font-semibold">
	<span>Planificar fichajes y ventas</span><span aria-hidden="true">→</span>
</a>

<!-- Mismo par de datos que en Hoy y con la misma rejilla de filetes, para que las dos pantallas
     se lean igual. -->
<div class="border-line mt-1 grid grid-cols-2 border-y">
	<div class="border-line border-r py-2.5 pr-3">
		<Countdown to={data.closesAt} label="Cierra el mercado de la liga" bare />
	</div>
	<div class="py-2.5 pl-3">
		<div class="text-muted text-[11px] font-medium">Tu saldo</div>
		<div class="num mt-0.5 text-xl {cash < 0 ? 'text-down' : ''}">{money(cash, 2)}</div>
	</div>
</div>

<nav aria-label="Vistas de Mercado" class="bg-surface-2 mt-4 grid grid-cols-4 gap-1 rounded-xl p-1 text-xs">
	{#each [['recomendado', 'Para ti'], ['liga', 'En venta'], ['mias', 'Mis ventas'], ['laliga', 'Explorar']] as [key, label] (key)}
		{@const selected = key === 'recomendado' ? tab === 'recomendado' || tab === 'acierto' : key === 'liga' ? tab === 'liga' || tab === 'managers' : key === 'laliga' ? ['laliga', 'precio', 'chollos'].includes(tab) : tab === key}
		<button type="button" onclick={() => setTab(key as Tab)} aria-pressed={selected}
			class="min-h-11 rounded-lg px-1 font-medium {selected ? 'bg-surface text-fg' : 'text-muted hover:text-fg'}">{label}</button>
	{/each}
</nav>
{#if tab === 'liga' || tab === 'managers'}
	<div class="mt-3 flex flex-wrap gap-2" aria-label="Quién vende" role="group">
		{#each [['liga', `Vende la liga · ${data.league.length}`], ['managers', `Venden managers · ${data.managers.length}`]] as [key, label] (key)}
			<button onclick={() => setTab(key as Tab)} aria-pressed={tab === key} class="min-h-11 rounded-lg px-3 text-xs {tab === key ? 'bg-fg text-bg font-semibold' : 'bg-surface-2 text-muted'}">{label}</button>
		{/each}
	</div>
{:else if ['laliga', 'precio', 'chollos'].includes(tab)}
	<div class="mt-3 flex flex-wrap gap-2" aria-label="Explorar jugadores" role="group">
		{#each [['laliga', 'Tendencias'], ['precio', 'Por precio'], ['chollos', 'Chollos']] as [key, label] (key)}
			<button onclick={() => setTab(key as Tab)} aria-pressed={tab === key} class="min-h-11 rounded-lg px-3 text-xs {tab === key ? 'bg-fg text-bg font-semibold' : 'bg-surface-2 text-muted'}">{label}</button>
		{/each}
	</div>
{:else if tab === 'recomendado' || tab === 'acierto'}
	<button onclick={() => setTab(tab === 'acierto' ? 'recomendado' : 'acierto')} class="text-accent mt-1 min-h-11 text-xs font-medium">{tab === 'acierto' ? '← Volver a las recomendaciones' : 'Ver aciertos de las recomendaciones →'}</button>
{/if}
{#if tab === 'liga' || tab === 'managers'}
	<div class="mt-3 mb-2 flex flex-wrap gap-1 px-1 text-xs">
		{#each [['subida', 'Suben hoy'], ['semana', '7 días'], ['precio', 'Más baratos'], ['valor', 'Más valiosos']] as [k, label] (k)}
			<button aria-pressed={sort === k} class="min-h-11 rounded-lg px-3 {sort === k ? 'bg-accent text-black' : 'bg-surface-2 text-muted'}" onclick={() => (sort = k as typeof sort)}>{label}</button>
		{/each}
	</div>
{/if}

{#if tab === 'recomendado'}
	{#if data.recs.some((r) => !r.value_day)}
		<p class="border-line text-muted mt-4 border-b pb-4 text-sm" role="status">Estas recomendaciones aún no incluyen el nuevo análisis de duración y saldo. Aparecerá cuando se actualice el cálculo.</p>
	{/if}
	{#if missingEleven.length}
		<p class="border-line mt-4 border-b pb-4 text-sm leading-relaxed"><strong class="text-warn">Tu once está incompleto.</strong> Faltan {missingEleven.join(', ')}.
			<a href="/plantilla" class="text-accent underline">Revisar plantilla</a></p>
	{/if}
	{#if desfasadas}
		<p class="border-line text-warn mt-4 border-b pb-4 text-sm" role="status">Las recomendaciones son anteriores al último mercado. Revisa los importes cuando termine el próximo cálculo.</p>
	{/if}
	{#if cash < 0}
		<section class="border-line mt-5 border-b pb-5" aria-labelledby="cash-title">
			<h2 id="cash-title" class="text-lg font-semibold">Primero, recupera saldo</h2>
			<p class="text-muted mt-1 text-sm leading-relaxed">Necesitas ingresar <strong class="num text-fg">{money(-cash, 2)}</strong> para salir de negativo. Las oportunidades de compra siguen visibles para que puedas planificar.</p>
			{#if availableOffers > 0}
				<p class="text-muted mt-2 text-sm">Tus ofertas recibidas suman <span class="num text-fg">{money(availableOffers, 2)}</span>. Si aceptaras todas, el saldo sería <span class="num {cash + availableOffers < 0 ? 'text-down' : 'text-up'}">{money(cash + availableOffers, 2)}</span>.</p>
			{/if}
			<button class="text-accent mt-2 min-h-10 text-sm font-medium" onclick={() => setTab('mias')}>Revisar mis ventas</button>
		</section>
	{:else if plannedBids > 0}
		<p class="text-muted mt-4 text-sm">Pujas propuestas: <span class="num text-fg">{money(plannedBids, 2)}</span> · Quedarían <span class="num text-fg">{money(cash - plannedBids, 2)}</span> si las ganas todas.</p>
	{/if}
	{#if pos}
		<div class="text-muted mt-3 flex items-center justify-between px-1 text-xs">
			<span>Solo {POS_PLURAL[pos]?.toLowerCase() ?? 'esa posición'}</span>
			<a href="/mercado?ver=recomendado" class="text-accent">ver todos</a>
		</div>
	{/if}
	{#if pujar.length}
		<Section title="Merece la pena pujar" flush bare>
			{#snippet aside()}{calculadas}{/snippet}
			{#each pujar as r (r.id)}<RecCard rec={r} />{/each}
		</Section>
	{:else if !sinSaldo.length}
		<div class="card text-muted mt-4 p-4 text-sm">
			{#if !data.recs.length}
				Todavía no hay recomendaciones calculadas. Puedes consultar los jugadores en la pestaña Liga.
			{:else if pos}
				No hay pujas recomendadas para esta posición con los datos y el saldo actuales.
			{:else}
				No hay pujas recomendadas con los datos y el saldo actuales. Abre las operaciones descartadas para ver qué limita cada compra.
			{/if}
		</div>
	{/if}
	{#if sinSaldo.length}
		<Section title="Interesantes, si liberas saldo" flush bare>
			{#snippet aside()}{sinSaldo.length} oportunidades{/snippet}
			<p class="text-muted mb-2 text-xs leading-relaxed">El precio encaja con la estimación, pero ahora no caben en tu presupuesto. Vender cambia también tu once: revisa el encaje después.</p>
			{#each sinSaldo as r (r.id)}<RecCard rec={r} />{/each}
		</Section>
	{/if}

	{#if rebote.length}
		<Section title="Posible rebote" flush bare>
			{#snippet aside()}bajan, pero con motivo para girar{/snippet}
			{#each rebote as r (r.id)}<RecCard rec={r} />{/each}
		</Section>
	{/if}

	{#if !vender.length && data.sellAdvisor && (data.sellAdvisor.urgentCount > 0 || data.sellAdvisor.recommendedCount > 0)}
		<div class="mt-4">
			<Section title="Ventas aconsejadas en tu plantilla" flush bare>
				{#snippet aside()}
					<a href="/plantilla?ver=ventas" class="text-accent text-xs font-semibold hover:underline">
						Semáforo completo ({(data.sellAdvisor?.urgentCount ?? 0) + (data.sellAdvisor?.recommendedCount ?? 0)}) →
					</a>
				{/snippet}
				<div>
					{#each data.sellAdvisor.players.filter((p) => p.decision === 'urgent' || p.decision === 'recommended') as p (p.player_id)}
						<div class="border-line flex items-center justify-between gap-3 border-b px-1 py-3 last:border-0">
							<div class="flex items-center gap-2.5 min-w-0">
								<span class="size-2 shrink-0 rounded-full {p.decision === 'urgent' ? 'bg-down' : 'bg-warn'}"></span>
								<div class="min-w-0">
									<div class="flex items-center gap-1.5 flex-wrap">
										<a href="/jugador/{p.player_id}" class="font-bold text-sm text-fg truncate hover:underline">
											{p.nickname ?? p.name}
										</a>
										<span class="rounded px-1.5 py-0.5 text-[9px] font-black uppercase {POS_BADGE[p.position_id]}">
											{POS[p.position_id]}
										</span>
									</div>
									<div class="text-muted text-xs truncate">{p.action_summary}</div>
								</div>
							</div>
							<div class="shrink-0 text-right">
								<div class="num font-bold text-sm text-fg">{money(p.value, 1)}</div>
								<div class="num text-[11px] font-semibold {p.decision === 'urgent' ? 'text-rose-400' : 'text-amber-400'}">
									{p.decision === 'urgent' ? 'Véndelo' : 'Valóralo'}
								</div>
							</div>
						</div>
					{/each}
				</div>
			</Section>
		</div>
	{:else if vender.length}
		<Section title="Vender o mantener" flush bare>
			{#each ventas as r (r.id)}<RecCard rec={r} />{/each}
			{#if mantener.length}
				<details class="border-line border-b pb-3">
					<summary class="text-muted min-h-11 cursor-pointer py-3 text-sm">Mantener de momento · {mantener.length} jugadores</summary>
					{#each mantener as r (r.id)}<RecCard rec={r} />{/each}
				</details>
			{/if}
		</Section>
	{/if}

	{#if descartados.length}
		<section class="mt-5">
			<button class="text-muted mb-2 min-h-11 px-1 text-sm font-medium" aria-expanded={verDescartados} onclick={() => (verDescartados = !verDescartados)}>
				{verDescartados ? '▾' : '▸'} Descartados · {descartados.length}
			</button>
			{#if verDescartados}
				<div>
					{#each descartados as r (r.id)}<RecCard rec={r} />{/each}
				</div>
			{/if}
		</section>
	{/if}

	<p class="text-muted mt-4 px-1 text-xs leading-relaxed">
		Cada recomendación compara dos cifras: lo que hizo falta históricamente para ganar una subasta en tu liga y lo
		que se estima recuperar revendiendo y mejorando tu once. La puja orientativa no garantiza ganar; el máximo rentable incluye un margen del 3 %.
	</p>
{:else if tab === 'liga'}
	<p class="text-muted mb-2 px-1 text-xs leading-relaxed">
		Los vende la liga. Puja a ciegas: gana la puja más alta y <b>todos cierran a la vez</b>, a la hora indicada arriba.
		El valor grande es su <b>precio oficial de hoy</b> tras la actualización de las 00:15.
	</p>
	<div class="card overflow-hidden">
		{#each ordered(data.league) as m (m.market_id)}
			{@const diff1d = m.value_1d != null ? m.value - m.value_1d : 0}
			{@const pct1d = m.value_1d != null && m.value_1d > 0 ? ((m.value - m.value_1d) / m.value_1d) * 100 : 0}
			{@const trend = playerTrend(m.spark, m.value, m.value_1d)}
			<PlayerRow p={m} compareTo={sort === 'semana' ? 'value_7d' : 'value_1d'} wrapSub>
				{#snippet sub()}
					<span class="flex flex-wrap items-center gap-x-2 gap-y-1 mt-0.5">
						<!-- Racha de días subiendo o bajando -->
						<span class="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-bold border {trend.badgeCls}">
							{trend.streakLabel}
						</span>

						{#if recByPlayer.get(m.player_id)?.max_bid != null}
							<span class="text-accent text-xs">
								Máximo estimado: {money(recByPlayer.get(m.player_id)?.max_bid, 2)}
							</span>
						{/if}

						<!-- Recomendación algorítmica si merece la pena pujar -->
						{#if m.rec_verdict === 'pujar'}
							<span class="rounded bg-emerald-500/20 px-1.5 py-0.5 text-[10px] font-bold text-emerald-300 border border-emerald-500/40">
								Pujar
							</span>
						{/if}

						<!-- Disponibilidad y titularidad -->
						{#if m.suspended}
							<span class="rounded bg-rose-500/15 px-1.5 py-0.5 text-[10px] font-bold text-rose-400">Sancionado</span>
						{:else if m.injured}
							<span class="rounded bg-rose-500/15 px-1.5 py-0.5 text-[10px] font-bold text-rose-400">Lesionado</span>
						{:else if m.start_prob != null}
							<span class="text-[11px] font-medium {m.start_prob >= 0.8 ? 'text-emerald-400' : m.start_prob >= 0.5 ? 'text-amber-400' : 'text-muted'}">
								{Math.round(m.start_prob * 100)}% titular
							</span>
						{/if}

						<!-- Pujas activas -->
						{#if m.num_bids}
							<span class="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-bold text-warn">
								{m.num_bids} puja{m.num_bids === 1 ? '' : 's'}
							</span>
						{/if}

						<!-- Rivales a los que les falta esa posición y les llega el saldo (radar) -->
						{#if data.contenders[m.player_id]?.length}
							<span class="text-warn text-[11px]" title="Les falta esa posición para alinear y su saldo estimado llega al precio">
								Lo necesita{data.contenders[m.player_id].length > 1 ? 'n' : ''}: {data.contenders[m.player_id].join(', ')}
							</span>
						{/if}

						<!-- Próximo rival -->
						{#if m.next_match}
							<span class="text-muted text-[11px]">{m.next_match.home ? 'vs' : 'en'} {m.next_match.opponent}</span>
						{/if}

						<!-- Puntos totales y media -->
						<span class="text-muted text-[11px]">{m.points_total} pts · {num(m.average_points, 1)} media</span>
					</span>
				{/snippet}
				{#snippet right()}
					<!-- Valor oficial ACTUALIZADO hoy a las 00:15 -->
					<span class="num text-[15px] font-bold {m.value > cash ? 'text-muted' : 'text-fg'}">
						{money(m.value)}
					</span>
					<!-- Cuánto subió o bajó hoy exactamente -->
					<span class="num text-[11px] font-semibold {diff1d > 0 ? 'text-up' : diff1d < 0 ? 'text-down' : 'text-muted'}">
						{signed(diff1d)}{#if m.value_1d != null} <span class="opacity-80">({pctText(pct1d)})</span>{/if}
					</span>
					<!-- Pujas activas en la subasta si existen -->
					{#if m.num_bids}
						<span class="text-[10px] font-bold text-warn">
							{m.num_bids} puja{m.num_bids === 1 ? '' : 's'}
						</span>
					{/if}
				{/snippet}
			</PlayerRow>
		{:else}
			<p class="text-muted p-3 text-sm">El mercado de la liga está cerrado ahora mismo. Vuelve a abrir en el próximo ciclo.</p>
		{/each}
	</div>
{:else if tab === 'managers'}
	<p class="text-muted mb-2 px-1 text-xs leading-relaxed">
		Los venden otros managers de tu liga con oferta directa. <b>Cada uno tiene su propio plazo de caducidad</b>.
	</p>
	<div class="card overflow-hidden">
		{#each ordered(data.managers) as m (m.market_id)}
			{@const diff1d = m.value_1d != null ? m.value - m.value_1d : 0}
			{@const pct1d = m.value_1d != null && m.value_1d > 0 ? ((m.value - m.value_1d) / m.value_1d) * 100 : 0}
			{@const gap = m.sale_price - m.value}
			{@const trend = playerTrend(m.spark, m.value, m.value_1d)}
			<PlayerRow p={m} compareTo={sort === 'semana' ? 'value_7d' : 'value_1d'} wrapSub>
				{#snippet sub()}
					<span class="flex flex-wrap items-center gap-x-2 gap-y-1 mt-0.5">
						<span class="text-muted text-[11px]">Vende <b class="text-fg">{m.seller}</b></span>

						<!-- Racha de días subiendo o bajando -->
						<span class="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-bold border {trend.badgeCls}">
							{trend.streakLabel}
						</span>

						<!-- Proyección a 7 días -->
						{#if m.value_7d != null}
							<span class="text-muted text-xs">
								Últimos 7 días: {signed(m.value - m.value_7d)}
							</span>
						{/if}

						<!-- Disponibilidad -->
						{#if m.suspended}
							<span class="rounded bg-rose-500/15 px-1.5 py-0.5 text-[10px] font-bold text-rose-400">Sancionado</span>
						{:else if m.injured}
							<span class="rounded bg-rose-500/15 px-1.5 py-0.5 text-[10px] font-bold text-rose-400">Lesionado</span>
						{:else if m.start_prob != null}
							<span class="text-[11px] font-medium {m.start_prob >= 0.8 ? 'text-emerald-400' : m.start_prob >= 0.5 ? 'text-amber-400' : 'text-muted'}">
								{Math.round(m.start_prob * 100)}% titular
							</span>
						{/if}

						<span class="text-muted text-[11px]">caduca {relative(m.expires_at)}</span>
					</span>
				{/snippet}
				{#snippet right()}
					<!-- Valor oficial ACTUALIZADO hoy a las 00:15 -->
					<span class="num text-[15px] font-bold {m.sale_price > cash ? 'text-muted' : 'text-fg'}">
						{money(m.value)}
					</span>
					<!-- Cuánto subió o bajó hoy exactamente -->
					<span class="num text-[11px] font-semibold {diff1d > 0 ? 'text-up' : diff1d < 0 ? 'text-down' : 'text-muted'}">
						{signed(diff1d)}{#if m.value_1d != null} <span class="opacity-80">({pctText(pct1d)})</span>{/if}
					</span>
					<!-- Lo que pide el rival -->
					<span class="text-[10px] font-medium {gap > 0 ? 'text-rose-400' : gap < 0 ? 'text-emerald-400' : 'text-muted'}">
						Pide {money(m.sale_price)} ({gap > 0 ? `+${money(gap)}` : gap < 0 ? `-${money(Math.abs(gap))}` : 'al valor'})
					</span>
				{/snippet}
			</PlayerRow>
		{:else}
			<p class="text-muted p-3 text-sm">Ningún manager tiene jugadores a la venta ahora mismo.</p>
		{/each}
	</div>
	<p class="text-muted mt-2 px-1 text-xs">Precio en gris: por encima de tu saldo de {money(cash)}.</p>
{:else if tab === 'mias'}
	<Section title="Lo que estás vendiendo" flush bare>
		{#snippet aside()}oferta recibida y coste de esperar{/snippet}
		{#each data.listings as m (m.market_id)}
			{@const perDia = m.value_1d != null ? m.value - m.value_1d : null}
			<div class="border-line border-b px-3 py-3 last:border-0">
				<div class="flex items-start justify-between gap-3">
					<div class="min-w-0">
						<a href="/jugador/{m.player_id}" class="font-medium">{m.nickname ?? m.name}</a>
						<div class="text-muted mt-0.5 text-xs">Vale {money(m.value, 2)} · pides {money(m.sale_price, 2)}</div>
					</div>
					<div class="shrink-0 text-right">
						{#if m.num_offers}
							<div class="text-up num font-semibold">{m.num_offers} oferta{m.num_offers === 1 ? '' : 's'}</div>
							<div class="text-muted text-xs">importe solo en la app oficial</div>
						{:else}
							<div class="text-muted text-sm">sin ofertas</div>
						{/if}
					</div>
				</div>
				<div class="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs">
					<span class="text-muted">Caduca {relative(m.expires_at)}</span>
					{#if perDia != null}
						<span class={perDia >= 0 ? 'text-up' : 'text-down'}>
							{perDia >= 0 ? 'Sube' : 'Baja'} {money(Math.abs(perDia))} al día
						</span>
					{/if}
					{#if m.falling_days > 2}
						<span class="text-down">{m.falling_days} días seguidos bajando</span>
					{/if}
					{#if m.value_7d != null}<span class="text-muted">7 días {signed(m.value - m.value_7d)}</span>{/if}
				</div>
				{#if m.falling_days >= 8}
					<p class="text-down mt-2 text-xs">
						Históricamente, tras 8 o más días seguidos de caída el valor bajó otro 10,4 % de media en la semana siguiente
						y solo subió el 6,7 % de las veces. Esperar una oferta mejor va en contra del dato: la oferta del sistema sigue al valor.
					</p>
				{/if}
			</div>
		{:else}
			<p class="text-muted p-3 text-sm">No tienes ningún jugador a la venta.</p>
		{/each}
	</Section>
{:else if tab === 'acierto'}
	<Accuracy data={data.acierto} />

{:else if tab === 'chollos'}
	{#if pos}
		<div class="mt-3 flex items-center gap-2 px-1 text-xs">
			<span class="chip bg-accent text-black">Solo {POS_PLURAL[pos] ?? 'una posición'}</span>
			<a href="/mercado?ver=chollos" class="text-muted">quitar el filtro</a>
		</div>
	{/if}

	<Section title="Rinden más de lo que cuestan" flush bare>
		{#snippet aside()}frente a los de su precio{/snippet}
		{#each dePosicion(data.chollos.mejores) as b (b.player_id)}
			<!-- Sin snippet `right` a propósito: ahí va el precio, que es la mitad de la comparación.
			     Sustituyéndolo, la lista decía "rinde 27 puntos de más" sin decir de más que cuánto. -->
			<PlayerRow p={b}>
				{#snippet sub()}{b.owner_is_me ? 'tuyo' : b.owner ? `de ${b.owner}` : 'libre'} · <span class="text-up">{b.points_total} pts, {num(b.surplus, 0)} más de lo esperado</span>{/snippet}
			</PlayerRow>
		{/each}
		<p class="text-muted px-3 py-2 text-[11px] leading-snug">
			Cada uno comparado con los de su misma posición que cuestan lo mismo. Puntos por millón a
			secas no vale: es ordenar por barato, porque los baratos hacen seis veces más puntos por millón
			que los caros. Dice lo que han rendido, no lo que rendirán.
		</p>
	</Section>

	<Section title="Rinden menos de lo que cuestan" flush bare>
		{#snippet aside()}los que no compensan{/snippet}
		{#each dePosicion(data.chollos.peores) as b (b.player_id)}
			<PlayerRow p={b}>
				{#snippet sub()}{b.owner_is_me ? 'tuyo' : b.owner ? `de ${b.owner}` : 'libre'} · <span class="text-down">{b.points_total} pts, {num(Math.abs(b.surplus), 0)} menos de lo esperado</span>{/snippet}
			</PlayerRow>
		{/each}
	</Section>

{:else if tab === 'precio'}
	<div class="mt-3 mb-2 px-1">
		<p class="text-muted text-xs leading-relaxed">
			Ranking para explorar por tramo de precio: mezcla media de puntos, titularidad, rendimiento frente a su precio y balón parado con pesos fijos. Es orientativo y no está contrastado hacia atrás; para decidir una puja, mira <a href="/mercado?ver=recomendado" class="text-accent">Para ti</a>.
		</p>
	</div>

	<!-- Tramos de precio -->
	<div class="mt-2 flex items-center gap-1.5 overflow-x-auto pb-1 text-xs scrollbar-none">
		{#each [
			['all', 'Todos los tramos'],
			['low', '< 5 M'],
			['mid', '5-15 M'],
			['high', '15-30 M'],
			['premium', '> 30 M']
		] as [tKey, tLabel] (tKey)}
			<button
				class="shrink-0 rounded-lg px-3 py-1.5 font-medium transition-all {pickTier === tKey ? 'bg-accent text-black font-bold shadow-xs' : 'bg-surface-2 text-muted hover:text-fg'}"
				onclick={() => (pickTier = tKey as PriceFilter)}
			>
				{tLabel}
			</button>
		{/each}
	</div>

	<!-- Selector de posición + Orden -->
	<div class="mt-2.5 flex flex-wrap items-center justify-between gap-2">
		<div class="flex items-center gap-1 overflow-x-auto text-[11px] scrollbar-none">
			{#each [[0, 'Todas'], [1, 'POR'], [2, 'DEF'], [3, 'MED'], [4, 'DEL']] as [pId, label] (pId)}
				<button
					class="shrink-0 rounded-md px-2.5 py-1 font-semibold transition-colors {pickPos === pId ? 'bg-fg text-bg' : 'bg-surface-2/80 text-muted border border-line hover:text-fg'}"
					onclick={() => (pickPos = pId as number)}
				>
					{label}
				</button>
			{/each}
		</div>

		<div class="flex items-center gap-1 text-[11px]">
			<span class="text-muted text-[10px]">Ordenar:</span>
			{#each [
				['score', 'Índice'],
				['puntos', 'Media'],
				['precio', 'Precio'],
				['subida', 'Subida']
			] as [sKey, sLabel] (sKey)}
				<button
					class="rounded px-2 py-0.5 transition-colors {pickSort === sKey ? 'bg-surface font-bold text-fg border border-line shadow-2xs' : 'text-muted hover:text-fg'}"
					onclick={() => (pickSort = sKey as typeof pickSort)}
				>
					{sLabel}
				</button>
			{/each}
		</div>
	</div>

	<!-- Lista de fichajes recomendados -->
	<div class="mt-3 space-y-2.5">
		{#each pickList as p, i (p.player_id)}
			{@const subidaHoy = p.value_1d != null ? p.value - p.value_1d : null}
			<div class="bg-surface border-line relative overflow-hidden rounded-xl border p-3.5 shadow-xs transition-all hover:border-fg/20">
				<!-- Cabecera de la tarjeta: Ranking, tramo y acción comparar -->
				<div class="flex items-center justify-between gap-2 pb-2 border-b border-line/60 text-xs">
					<div class="flex items-center gap-2">
						<span class="num font-black text-muted text-xs">#{i + 1}</span>
						<span class="rounded px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider
							{p.tier === 'low' ? 'bg-sky-500/15 text-sky-400 border border-sky-500/30' :
							 p.tier === 'mid' ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30' :
							 p.tier === 'high' ? 'bg-amber-500/15 text-amber-400 border border-amber-500/30' :
							 'bg-purple-500/15 text-purple-400 border border-purple-500/30'}">
							{p.tier === 'low' ? '< 5 M · Parche' :
							 p.tier === 'mid' ? '5 - 15 M · Titular' :
							 p.tier === 'high' ? '15 - 30 M · Estrella' :
							 '> 30 M · Crack'}
						</span>
						{#if p.surplus && p.surplus > 0}
							<span class="bg-up/10 text-up border border-up/25 rounded px-1.5 py-0.5 text-[10px] font-bold num" title="Puntos esperados por encima del coste de su posición">
								+{num(p.surplus, 1)} vs coste
							</span>
						{/if}
					</div>

					<a
						href="/comparar?p1={p.player_id}"
						class="text-muted hover:text-fg text-[11px] font-medium flex items-center gap-1 bg-surface-2/60 hover:bg-surface-2 px-2 py-1 rounded transition-colors"
					>
						<span>Comparar</span>
					</a>
				</div>

				<!-- Datos del jugador -->
				<div class="mt-2.5 flex items-center gap-3">
					<a href="/jugador/{p.player_id}" class="relative shrink-0 group">
						{#if p.image_url}
							<img
								src={p.image_url}
								alt={p.nickname ?? p.name}
								class="h-11 w-11 rounded-full border-2 bg-surface-2 object-cover {POS_BORDER[p.position_id] ?? 'border-line'} transition-transform group-hover:scale-105"
								loading="lazy"
							/>
						{:else}
							<div class="num flex h-11 w-11 items-center justify-center rounded-full border-2 bg-surface-2 text-xs font-bold text-muted {POS_BORDER[p.position_id] ?? 'border-line'}">
								{POS[p.position_id] ?? '?'}
							</div>
						{/if}
						{#if p.badge_url}
							<img src={p.badge_url} alt={p.club} class="absolute -bottom-1 -right-1 h-5 w-5 object-contain drop-shadow" />
						{/if}
					</a>

					<div class="min-w-0 flex-1">
						<div class="flex items-center gap-1.5 flex-wrap">
							<a href="/jugador/{p.player_id}" class="truncate text-sm font-bold text-fg hover:underline">
								{p.nickname ?? p.name}
							</a>
							<span class="rounded px-1.5 py-0.5 text-[10px] font-black uppercase {POS_BADGE[p.position_id]}">
								{POS[p.position_id]}
							</span>
							<span class="text-muted text-xs font-medium">
								{shortClub(p.club)}
							</span>
						</div>

						<!-- Responsabilidades a balón parado -->
						<div class="mt-1 flex items-center gap-1.5 flex-wrap text-[10px]">
							{#if p.pen_taken > 0}
								<span class="bg-surface-2 text-fg border border-line rounded px-1.5 py-0.5 font-medium flex items-center gap-0.5">
									Penaltis ({p.pen_taken})
								</span>
							{/if}
							{#if p.corner_taken > 2}
								<span class="bg-surface-2 text-fg border border-line rounded px-1.5 py-0.5 font-medium flex items-center gap-0.5">
									Córners ({p.corner_taken})
								</span>
							{/if}
							{#if p.fault_taken > 1}
								<span class="bg-surface-2 text-fg border border-line rounded px-1.5 py-0.5 font-medium flex items-center gap-0.5">
									Faltas ({p.fault_taken})
								</span>
							{/if}
						</div>
					</div>

					<div class="shrink-0 text-right">
						<div class="num text-base font-extrabold text-fg">{money(p.value, 1)}</div>
						{#if subidaHoy != null && subidaHoy !== 0}
							<div class="num text-[11px] font-bold {subidaHoy > 0 ? 'text-up' : 'text-down'}">
								{subidaHoy > 0 ? '▲' : '▼'} {signed(subidaHoy, 1)}
							</div>
						{/if}
					</div>
				</div>

				<!-- Rejilla de métricas clave (4 columnas) -->
				<div class="bg-surface-2/50 border-line mt-3 grid grid-cols-4 rounded-lg border p-2 text-center text-xs">
					<div>
						<div class="text-muted text-[10px] font-medium">Media / J</div>
						<div class="num font-bold text-fg mt-0.5 text-sm">{num(p.average_points, 1)}</div>
					</div>
					<div>
						<div class="text-muted text-[10px] font-medium">Titularidad</div>
						<div class="num font-bold mt-0.5 text-sm {p.injured ? 'text-down' : p.suspended ? 'text-down' : (p.start_prob ?? 0.5) >= 0.7 ? 'text-up' : 'text-warn'}">
							{#if p.injured}
								Lesión
							{:else if p.suspended}
								Sanción
							{:else if p.start_prob != null}
								{Math.round(p.start_prob * 100)} %
							{:else}
								–
							{/if}
						</div>
					</div>
					<div>
						<div class="text-muted text-[10px] font-medium">Puntos Tot.</div>
						<div class="num font-bold text-fg mt-0.5 text-sm">{p.points_total}</div>
					</div>
					<div>
						<div class="text-muted text-[10px] font-medium">Índice</div>
						<div class="num font-bold text-accent mt-0.5 text-sm">{num(p.score, 1)}</div>
					</div>
				</div>

				<!-- Estado en tu liga privada + Próximo partido -->
				<div class="mt-2.5 flex items-center justify-between gap-2 pt-2 border-t border-line/50 text-[11px]">
					<div class="flex items-center gap-1.5 truncate">
						{#if p.owner_is_me}
							<span class="inline-flex items-center gap-1 rounded bg-accent/20 px-1.5 py-0.5 font-bold text-accent text-[10px]">
								En tu plantilla
							</span>
						{:else if p.sale_price}
							<span class="inline-flex items-center gap-1 rounded bg-amber-500/15 border border-amber-500/30 px-1.5 py-0.5 font-bold text-amber-400 text-[10px]">
								En mercado por {money(p.sale_price, 1)}
							</span>
						{:else if p.owner}
							<span class="text-muted text-[10px] truncate max-w-[140px]">
								De {p.owner}
							</span>
						{:else}
							<span class="text-muted/70 text-[10px] font-medium">
								Libre
							</span>
						{/if}
					</div>

					{#if p.next_match}
						<div class="text-muted text-[10px] shrink-0 font-medium">
							Próximo: <span class="text-fg font-semibold">{p.next_match.home ? '(C)' : '(F)'}</span> vs {p.next_match.opponent}
						</div>
					{/if}
				</div>
			</div>
		{:else}
			<p class="card text-muted p-5 text-center text-xs">No hay jugadores recomendados con los filtros seleccionados.</p>
		{/each}
	</div>

{:else}
	<!-- Header estadístico del mercado -->
	<div class="card bg-surface-2/40 border-line mt-3 p-3 text-xs">
		<div class="flex items-center justify-between">
			<div class="flex items-center gap-1.5 font-semibold text-fg">
				<span>Mercado de Primera División</span>
			</div>
			<div class="num flex items-center gap-2 text-[11px]">
				<span class="text-up font-bold">▲ {data.radar.total_up} suben</span>
				<span class="text-muted">·</span>
				<span class="text-down font-bold">▼ {data.radar.total_down} bajan</span>
			</div>
		</div>
	</div>

	<!-- Selector de Sentido (Subidas / Bajadas) y Métrica (€ / %) -->
	<div class="mt-3 flex flex-wrap items-center justify-between gap-2">
		<!-- Subidas / Bajadas -->
		<div class="bg-surface-2 flex rounded-lg p-0.5 text-xs font-semibold">
			<button
				class="rounded-md px-3 py-1.5 transition-all {moverDir === 'up' ? 'bg-up/20 text-up border border-up/40 shadow-xs' : 'text-muted hover:text-fg'}"
				onclick={() => (moverDir = 'up')}
			>
				▲ Mayores Subidas
			</button>
			<button
				class="rounded-md px-3 py-1.5 transition-all {moverDir === 'down' ? 'bg-down/20 text-down border border-down/40 shadow-xs' : 'text-muted hover:text-fg'}"
				onclick={() => (moverDir = 'down')}
			>
				▼ Mayores Bajadas
			</button>
		</div>

		<!-- En Euros vs En Porcentaje -->
		<div class="bg-surface-2 flex rounded-lg p-0.5 text-[11px] font-medium">
			<button
				class="rounded-md px-2.5 py-1 transition-all {moverMetric === 'eur' ? 'bg-surface text-fg font-bold shadow-xs' : 'text-muted hover:text-fg'}"
				onclick={() => (moverMetric = 'eur')}
			>
				Euros (€)
			</button>
			<button
				class="rounded-md px-2.5 py-1 transition-all {moverMetric === 'pct' ? 'bg-surface text-fg font-bold shadow-xs' : 'text-muted hover:text-fg'}"
				onclick={() => (moverMetric = 'pct')}
			>
				Porcentaje (%)
			</button>
		</div>
	</div>

	<!-- Selector de posiciones -->
	<div class="mt-2.5 mb-2 flex items-center gap-1 overflow-x-auto pb-0.5 text-[11px] scrollbar-none">
		{#each [[0, 'Todas'], [1, 'Porteros'], [2, 'Defensas'], [3, 'Centrocampistas'], [4, 'Delanteros']] as [pId, label] (pId)}
			<button
				class="shrink-0 rounded-md px-2.5 py-1 transition-colors {moverPos === pId ? 'bg-fg text-bg font-bold' : 'bg-surface-2/70 text-muted border border-line hover:text-fg'}"
				onclick={() => (moverPos = pId as number)}
			>
				{label}
			</button>
		{/each}
	</div>

	<!-- Lista de jugadores en el ranking -->
	<div class="card mt-2 divide-line divide-y overflow-hidden shadow-sm">
		{#each moverList as p, i (p.player_id)}
			<a
				href="/jugador/{p.player_id}"
				class="active:bg-surface-2/60 flex items-center gap-2.5 p-2.5 transition-colors hover:bg-surface-2/30"
			>
				<!-- Ranking # -->
				<span class="num text-muted w-5 shrink-0 text-center text-xs font-bold opacity-75">
					#{i + 1}
				</span>

				<!-- Avatar con borde de posición -->
				<div class="relative shrink-0">
					{#if p.image_url}
						<img
							src={p.image_url}
							alt={p.nickname ?? p.name}
							class="h-9 w-9 rounded-full border-2 bg-surface-2 object-cover {POS_BORDER[p.position_id] ?? 'border-line'}"
							loading="lazy"
						/>
					{:else}
						<div class="num flex h-9 w-9 items-center justify-center rounded-full border-2 bg-surface-2 text-xs font-bold text-muted {POS_BORDER[p.position_id] ?? 'border-line'}">
							{POS[p.position_id] ?? '?'}
						</div>
					{/if}
				</div>

				<!-- Info principal: Nombre + Club + Dueño -->
				<div class="min-w-0 flex-1">
					<div class="flex items-center gap-1.5">
						<span class="truncate text-sm font-semibold text-fg">{p.nickname ?? p.name}</span>
						<span class="num text-[10px] text-muted shrink-0 font-medium">{shortClub(p.club)}</span>
					</div>
					<div class="mt-0.5 flex items-center gap-2 text-[11px]">
						<span class="num text-muted font-medium">{money(p.value, 1)}</span>
						{#if p.owner_is_me}
							<span class="rounded bg-accent/20 px-1 py-px text-[10px] font-bold text-accent">Tuyo</span>
						{:else if p.owner}
							<span class="text-muted text-[10px] truncate max-w-[120px]">de {p.owner}</span>
						{:else}
							<span class="text-muted/60 text-[10px]">Libre</span>
						{/if}
					</div>
				</div>

				<!-- Chapa de Subida / Bajada -->
				<div class="shrink-0 text-right">
					<div
						title="{p.diff_1d > 0 ? '+' : ''}{p.diff_1d.toLocaleString('es-ES')} € hoy"
						class="num inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-bold {p.diff_1d > 0 ? 'bg-up/15 text-up border border-up/30' : p.diff_1d < 0 ? 'bg-down/15 text-down border border-down/30' : 'bg-surface-2 text-muted'}"
					>
						<span>{p.diff_1d > 0 ? '▲' : p.diff_1d < 0 ? '▼' : '–'}</span>
						<span>{signed(p.diff_1d, 1)}</span>
						{#if p.pct_1d != null}
							<span class="text-[10px] opacity-80 font-normal">({p.pct_1d > 0 ? '+' : ''}{p.pct_1d.toFixed(1)}%)</span>
						{/if}
					</div>
					{#if p.diff_7d != null && p.diff_7d !== 0}
						<div class="num text-muted mt-0.5 text-[10px]">
							7d: {signed(p.diff_7d, 1)}
						</div>
					{/if}
				</div>
			</a>
		{:else}
			<p class="text-muted p-4 text-center text-xs">No hay jugadores con este filtro.</p>
		{/each}
	</div>
{/if}
