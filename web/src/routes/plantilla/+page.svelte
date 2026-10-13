<script lang="ts">
	import { page } from '$app/state';
	import Delta from '$lib/components/Delta.svelte';
	import Eleven from '$lib/components/Eleven.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import SellAdvisor from '$lib/components/SellAdvisor.svelte';
	import SquadList from '$lib/components/SquadList.svelte';
	import { money, pct, pctText, signed } from '$lib/format';
	let { data } = $props();
	const total = $derived(data.players.reduce((a, p) => a + p.value, 0));
	const total1d = $derived(data.players.reduce((a, p) => a + (p.value_1d ?? p.value), 0));
	const total7d = $derived(data.players.reduce((a, p) => a + (p.value_7d ?? p.value), 0));
	const plus = $derived(data.players.reduce((a, p) => a + (p.bought_for != null ? p.value - p.bought_for : 0), 0));
	const plusKnown = $derived(data.players.filter((p) => p.bought_for != null).length);
	const byPos = $derived([1, 2, 3, 4].map((pos) => data.players.filter((p) => p.position_id === pos && p.status !== 'out_of_league').length));
	// Lo que exige cualquiera de las siete formaciones del juego. Mismos mínimos que
	// `analysis/eleven.MINIMOS`: sin esto no hay once válido que alinear.
	const MINIMOS: [number, number, string, string][] = [
		[1, 1, 'portero', 'porteros'],
		[2, 3, 'defensa', 'defensas'],
		[3, 3, 'medio', 'medios'],
		[4, 1, 'delantero', 'delanteros']
	];
	const hayAyer = $derived(data.players.some((p) => p.value_1d != null));
	const disponibles = $derived(data.players.filter((p) => p.status !== 'injured' && p.status !== 'suspended'));
	const falta = $derived(
		MINIMOS.flatMap(([pos, minimo, singular, plural]) => {
			const n = disponibles.filter((p) => p.position_id === pos).length;
			return n < minimo ? [`${minimo - n} ${minimo - n === 1 ? singular : plural}`] : [];
		})
	);
	const hueco = $derived(
		MINIMOS.find(([pos, minimo]) => disponibles.filter((p) => p.position_id === pos).length < minimo)?.[0] ?? 0
	);

	type Tab = 'plantilla' | 'once' | 'ventas';
	const TABS: Tab[] = ['plantilla', 'once', 'ventas'];
	let selectedTab = $state<Tab>('plantilla');

	$effect(() => {
		const param = page.url.searchParams.get('ver');
		if (param && TABS.includes(param as Tab)) selectedTab = param as Tab;
	});

	const tab = $derived(selectedTab);

	function setTab(k: Tab) {
		selectedTab = k;
		if (typeof window !== 'undefined') {
			const u = new URL(window.location.href);
			u.searchParams.set('ver', k);
			window.history.replaceState({}, '', u);
		}
	}
</script>

<svelte:head><title>lfm · Plantilla</title></svelte:head>

<PageHeader title="Plantilla" fresh={data.fresh} shows="plantilla" />

<div class="bg-surface-2 mt-3 flex rounded-xl p-1 text-xs">
	{#each [
		['plantilla', `Plantilla · ${data.players.length}`],
		['once', data.once ? `Once · ${data.once.formation}` : 'Once'],
		['ventas', data.sellAdvisor?.urgentCount ? `Ventas · ${data.sellAdvisor.urgentCount}` : 'Ventas']
	] as [k, label] (k)}
		<button
			type="button"
			onclick={() => setTab(k as Tab)}
			class="flex-1 rounded-lg py-1.5 text-center transition-colors cursor-pointer {tab === k ? 'bg-surface font-semibold text-fg shadow-xs' : 'text-muted hover:text-fg'}"
		>
			{label}
		</button>
	{/each}
</div>

<!-- Rejilla de tres con filetes, como el tablero: sin caja, y cada cifra con su palabra encima
     y su matiz debajo. -->
<div class="border-line grid grid-cols-3 border-y">
	<div class="border-line border-r px-1 py-2.5">
		<div class="text-muted text-[11px]">Valor</div>
		<div class="num mt-0.5 text-[19px] font-medium">{money(total)}</div>
		<!-- Un «0 €» no es un cero, es un hueco disfrazado de dato: si falta la foto del día anterior
		     —el 15 de septiembre falló el job— el total caía a cero y parecía que nada se había movido. -->
		{#if hayAyer}
			<Delta now={total} before={total1d} showPct={false} size="text-[11px]" />
		{:else}
			<div class="text-muted text-[11px]">sin dato de ayer</div>
		{/if}
	</div>
	<div class="border-line border-r px-2 py-2.5">
		<div class="text-muted text-[11px]">7 días</div>
		<div class="num mt-0.5 text-[19px] font-medium {total >= total7d ? 'text-up' : 'text-down'}">
			{signed(total - total7d)}
		</div>
		<div class="text-muted text-[11px]">{pctText(pct(total, total7d))}</div>
	</div>
	<div class="px-2 py-2.5">
		<div class="text-muted text-[11px]">Plusvalía</div>
		<div class="num mt-0.5 text-[19px] font-medium {plus >= 0 ? 'text-up' : 'text-down'}">{signed(plus)}</div>
		<div class="text-muted text-[11px]">valor − pagado · {plusKnown}/{data.players.length}</div>
	</div>
</div>

<div class="text-muted flex flex-wrap items-center gap-x-3 px-1 py-2 text-[11px]">
	<span>{byPos[0]} POR · {byPos[1]} DEF · {byPos[2]} MED · {byPos[3]} DEL</span>
	{#if data.once?.feasible}<span
			>{data.once.feasible === 1 ? 'una sola formación posible' : `${data.once.feasible} formaciones posibles`}</span
		>{/if}
	{#if data.team.team_money != null}<span>saldo {money(data.team.team_money, 2)}</span>{/if}
</div>

{#if tab === 'once'}
	<a href="/planificar" class="border-line text-accent mt-3 flex min-h-11 items-center justify-between border-b px-1 text-sm font-semibold">
		<span>Probar fichajes y ventas para tu once</span><span aria-hidden="true">→</span>
	</a>
	{#if data.once}
		<Eleven once={data.once} />
	{:else if falta.length}
		<!-- Decir «todavía no hay once calculado» cuando lo que pasa es que **no tienes portero** es lo
		     contrario de ayudar: ese hueco son cero puntos y solo se arregla fichando. -->
		<div class="border-down/40 bg-down/10 mt-4 rounded-xl border p-4">
			<p class="text-down text-sm font-semibold">No puedes alinear un once: te falta {falta.join(' y ')}.</p>
			<p class="text-muted mt-2 text-xs leading-snug">
				Cualquier formación del juego necesita un portero, tres defensas, tres medios y un
				delantero. Ese hueco son cero puntos en la jornada, y solo se arregla fichando.
			</p>
			<a href="/mercado?ver=chollos{hueco ? `&pos=${hueco}` : ''}" class="bg-surface-2 mt-3 inline-block rounded-lg px-3 py-1.5 text-xs font-medium">
				Ver quién hay en el mercado →
			</a>
		</div>
	{:else}
		<div class="card mt-4 p-4 text-sm leading-snug">
			Todavía no hay once calculado. Lo escribe el job diario; si acabas de fichar, aparecerá en la
			próxima pasada.
		</div>
	{/if}
{:else if tab === 'ventas'}
	{#if data.sellAdvisor}
		<div class="mt-4">
			<SellAdvisor advisor={data.sellAdvisor} />
		</div>
	{:else}
		<p class="card text-muted p-4 text-xs">Sin datos de análisis de ventas disponibles.</p>
	{/if}
{:else}
	<div class="mt-4">
		<SquadList players={data.players} />
	</div>
{/if}
