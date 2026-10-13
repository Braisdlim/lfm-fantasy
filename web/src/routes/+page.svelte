<script lang="ts">
	import Countdown from '$lib/components/Countdown.svelte';
	import Delta from '$lib/components/Delta.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import PlayerRow from '$lib/components/PlayerRow.svelte';
	import RiskRow from '$lib/components/RiskRow.svelte';
	import Section from '$lib/components/Section.svelte';
	import { hitText } from '$lib/watch-text';
	import { clauseState, clauseVsValueShort, money, relative, signed, STATUS, timeText } from '$lib/format';
	let { data } = $props();
	const t = $derived(data.team);

	const saldo = $derived(t?.team_money ?? 0);
	const actionsStale = $derived(!!(data.actionsAt && data.fresh?.market && new Date(data.fresh.market) > new Date(data.actionsAt)));
	const pagables = $derived(data.opportunities.filter((c) => c.buyout_clause <= saldo).toSorted((a, b) => b.gap - a.gap));
</script>

<svelte:head><title>lfm · Hoy</title></svelte:head>

<PageHeader title="Hoy" fresh={data.fresh} shows="mercado" />

{#if !t}
	<div class="card text-muted mt-4 p-4">Aún no hay datos de tu liga. Vuelve a consultar cuando termine la próxima actualización.</div>
{:else}
	<!-- El diseño separa con filetes, no con cajas: el saldo manda por tamaño y el resto se
	     ordena a su alrededor sin marcos que compitan. -->
	<div class="flex items-end justify-between px-1 pt-1 pb-3">
		<div>
			<div class="text-muted text-xs font-medium">Saldo</div>
			<div class="num mt-0.5 text-4xl leading-none font-medium tracking-tighter">{money(t.team_money, 2)}</div>
		</div>
		<div class="pb-1 text-right">
			<div class="text-muted text-[11px]">{t.position}º de {t.managers} · {t.points} pts</div>
			<div class="text-muted mt-2 text-xs">Valor de plantilla</div><div class="num mt-0.5 text-[15px]">{money(t.team_value)}</div>
			<span class="text-muted mr-1 text-xs">Hoy</span><Delta now={data.squadValue} before={data.squadValue - data.squadDelta} size="text-xs" showPct={false} />
		</div>
	</div>

	<div class="border-line grid grid-cols-2 border-y">
		<div class="border-line border-r py-2.5 pr-3">
			<Countdown to={data.cal.closesAt} label="Cierra el mercado" bare />
		</div>
		<div class="py-2.5 pl-3">
			<Countdown to={data.cal.week?.opening_at ?? null} label="Bloqueo once · J{data.cal.week?.week ?? '?'}" bare />
		</div>
	</div>
	<div class="text-muted mt-2 px-1 text-xs">
		{#if data.protectedNow}
			<span class="text-up">Cláusulas protegidas</span> hasta que acabe la jornada.
		{:else if data.protectionStart && new Date(data.protectionStart).getTime() > Date.now()}
			Protección automática de cláusulas desde el {timeText(data.protectionStart)}. Hasta entonces, cualquiera con saldo puede clausular.
		{/if}
	</div>

	{#if data.actions.length || data.missingEleven.length}
		<Section title="Tus próximas decisiones" flush bare>
			{#snippet aside()}<a href="/mercado?ver=recomendado" class="text-accent">ver análisis completo</a>{/snippet}
			{#if actionsStale}
				<p class="text-warn border-line border-b px-1 pb-2 text-xs" role="status">El mercado cambió después de estas recomendaciones. Revisa los importes antes de decidir.</p>
			{/if}
			{#if data.missingEleven.length}
				<a href="/plantilla?ver=once" class="border-line flex min-h-14 items-center gap-3 border-b px-1 py-2.5 hover:bg-surface-2/50">
				<span class="text-warn w-11 shrink-0 text-[11px] font-semibold">ONCE</span>
				<span class="min-w-0 flex-1">
					<span class="block text-sm font-semibold">Te falta {data.missingEleven.join(' y ')}</span>
					<span class="text-muted block text-xs">Revisa el hueco antes del bloqueo de alineación</span>
				</span>
			</a>
			{/if}
			{#each data.actions as action (action.id)}
				<a href="/jugador/{action.player_id}" class="border-line flex min-h-14 items-center gap-3 border-b px-1 py-2.5 last:border-0 hover:bg-surface-2/50">
				<span class="w-11 shrink-0 text-[11px] font-semibold {action.kind === 'buy' ? 'text-up' : 'text-warn'}">{action.kind === 'buy' ? 'PUJAR' : 'VENDER'}</span>
				<span class="min-w-0 flex-1">
					<span class="block truncate text-sm font-semibold">{action.name}</span>
					<span class="text-muted block truncate text-xs">{action.reasons[0]?.text ?? (action.completes_eleven ? 'Completa tu once' : 'Ver razones y cifras')}</span>
				</span>
				{#if action.kind === 'buy' && action.bid_to_win != null}
					<span class="num shrink-0 text-xs font-medium">{money(action.bid_to_win)}</span>
				{/if}
			</a>
			{/each}
			{#if data.actionsAt}<p class="text-muted px-1 pt-2 text-[11px]">Calculadas {relative(data.actionsAt)}</p>{/if}
		</Section>
	{/if}

	{#if data.watchCount}<Section title="Lista de seguimiento" flush bare>
		{#snippet aside()}<a href="/seguimiento" class="text-accent">{data.watchCount ? `${data.watchCount} en la lista` : 'qué es'}</a>{/snippet}
		{#each data.watchReady as w (w.player_id)}
			<PlayerRow p={w} wrapSub>
				{#snippet sub()}{#each w.detail?.hits ?? [] as h (h.kind)}<span class="text-up block">{hitText(h)}{#if h.price > saldo}{' · '}<span class="text-down">te faltan {money(h.price - saldo)}</span>{/if}</span>{/each}{/snippet}
			</PlayerRow>
		{:else}
			<p class="text-muted px-1 text-xs">
				{data.watchCount
					? 'Ninguno de tu lista se puede fichar ahora a tu precio. Te aviso por Telegram cuando pase.'
					: 'Sigue jugadores desde su ficha y te aviso cuando estén en el mercado o con la cláusula abierta a tu precio.'}
			</p>
		{/each}
	</Section>
	{:else}<a href="/seguimiento" class="text-accent mt-3 flex min-h-11 items-center text-sm">Crear tu lista de seguimiento →</a>{/if}

	{#if data.risks.length}
		<Section title="Cláusulas en riesgo" flush bare>
			{#snippet aside()}{data.risks.length} en peligro{/snippet}
			{#each data.risks as r (r.player_id)}
				<RiskRow p={r} state={clauseState(r.clause_locked_until, r.is_shielded)} threats={r.threats} />
			{/each}
		</Section>
	{/if}

	{#if data.notPlaying.length}
		<Section title="Ojo en tu plantilla" flush bare>
			{#each data.notPlaying as p (p.player_id)}
				<PlayerRow {p}>
					{#snippet sub()}<span class={STATUS[p.status]?.cls}>{STATUS[p.status]?.label ?? p.status}</span>{#if p.next_match} · {p.next_match.home ? 'vs' : 'en'} {p.next_match.opponent}{/if}{/snippet}
				</PlayerRow>
			{/each}
		</Section>
	{/if}

	<Section title="Cláusulas a tu alcance" flush bare>
		{#snippet aside()}{pagables.length} abiertas{/snippet}
		{#each pagables.slice(0, 3) as c (c.player_id)}
			<PlayerRow p={c} wrapSub>
				{#snippet sub()}Abierta · de {c.owner}{/snippet}
				{#snippet right()}
					{@const g = clauseVsValueShort(c.gap, c.value)}
					<span class="num font-semibold">{money(c.buyout_clause)}</span>
					<span class="text-right text-xs {g.cls}">{g.text}</span>
				{/snippet}
			</PlayerRow>
		{:else}<p class="text-muted py-3 text-sm">No hay cláusulas abiertas que puedas pagar con tu saldo.</p>{/each}
		<a href="/liga?clausulas=alcance#clausulas" class="text-accent flex min-h-11 items-center px-1 text-sm font-medium">Ver todas las cláusulas y próximas aperturas →</a>
	</Section>

	<Section title="Tu plantilla hoy" flush bare>
		{#snippet aside()}<a href="/plantilla" class="text-accent">ver toda</a>{/snippet}
		{#each data.squadUp as p (p.player_id)}<PlayerRow {p} />{/each}
		{#if data.squadDown.length}<div class="border-line border-t"></div>{/if}
		{#each data.squadDown as p (p.player_id)}<PlayerRow {p} />{/each}
	</Section>

	{#if data.diary}
		<a href="/diario" class="border-line mt-5 flex min-h-14 items-center gap-3 border-y px-1 py-2.5 hover:bg-surface-2/50">
			<span class="min-w-0 flex-1">
				<span class="block text-sm font-semibold">Diario de decisiones</span>
				<span class="text-muted block text-xs">{data.diary.operations} operaciones · realizado <span class="num {data.diary.realized >= 0 ? 'text-up' : 'text-down'}">{signed(data.diary.realized, 1)}</span> · latente <span class="num {data.diary.unrealized >= 0 ? 'text-up' : 'text-down'}">{signed(data.diary.unrealized, 1)}</span></span>
			</span>
			<span class="text-accent text-xs">ver →</span>
		</a>
	{/if}

	<div class="border-line mt-5 flex flex-wrap gap-x-6 border-t pt-2 text-sm">
		<a href="/mercado?ver=liga" class="text-accent flex min-h-11 items-center">Ver mercado · {data.marketCount} en venta →</a>
		<a href="/mercado?ver=laliga" class="text-accent flex min-h-11 items-center">Tendencias del día →</a>
	</div>
{/if}
