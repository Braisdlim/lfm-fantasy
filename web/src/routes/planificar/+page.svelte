<script lang="ts">
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Section from '$lib/components/Section.svelte';
	import { bestEleven, projectScenario, type Choice } from '$lib/planner';
	import { fixed, money, POS, relative } from '$lib/format';
	let { data } = $props();

	// Importes en millones para poder editarlos en el móvil sin escribir seis ceros.
	let buyAmounts = $state<Record<string, number>>({});
	let sellAmounts = $state<Record<string, number>>({});
	let query = $state('');
	let position = $state(0);
	let activeList = $state<'buys' | 'sells'>('buys');
	const inMillions = (euros: number) => Math.ceil(euros / 1_000) / 1_000;
	const inEuros = (millions: number) => Math.round(millions * 1_000_000);
	const choices = (amounts: Record<string, number>): Choice[] =>
		Object.entries(amounts).map(([player_id, amount]) => ({ player_id, amount: inEuros(amount) }));
	const buys = $derived(choices(buyAmounts));
	const sells = $derived(choices(sellAmounts));
	const result = $derived(projectScenario(data.roster, data.candidates, data.cash ?? 0, buys, sells));
	const changed = $derived(buys.length > 0 || sells.length > 0);
	const buysById = $derived(new Set(buys.map((p) => p.player_id)));
	const sellersById = $derived(new Set(sells.map((p) => p.player_id)));
	const shownMarket = $derived(data.candidates.filter((p) =>
		(!position || p.position_id === position) &&
		(!query.trim() || `${p.name} ${p.club}`.toLocaleLowerCase('es-ES').includes(query.trim().toLocaleLowerCase('es-ES')))
	));
	const recommendationsStale = $derived(!!(
		data.recommendationsAt && data.fresh?.market &&
		new Date(data.fresh.market) > new Date(data.recommendationsAt)
	));

	function toggleBuy(id: string, suggested: number) {
		const next = { ...buyAmounts };
		if (id in next) delete next[id];
		else next[id] = inMillions(suggested);
		buyAmounts = next;
	}
	function toggleSell(id: string, value: number) {
		const next = { ...sellAmounts };
		if (id in next) delete next[id];
		else next[id] = inMillions(value);
		sellAmounts = next;
	}
	function reset() {
		buyAmounts = {};
		sellAmounts = {};
	}
	const baseline = $derived(bestEleven(data.roster));
</script>

<svelte:head><title>lfm · Planificar operaciones</title></svelte:head>

<PageHeader title="Planificar" back="/mercado" />
<p class="text-muted mt-1 text-sm leading-relaxed">Combina fichajes y ventas para ver el saldo y el mejor once que podrías formar. Es una simulación; ninguna operación se envía al juego.</p>

{#if recommendationsStale}
	<p class="text-warn border-line mt-4 border-b pb-3 text-xs" role="status">Las estimaciones son anteriores a la última captura del mercado. Revisa precios y disponibilidad.</p>
{/if}

<div class="border-line mt-5 grid grid-cols-2 border-y">
	<div class="border-line border-r py-3 pr-3">
		<div class="text-muted text-[11px]">Saldo tras el plan</div>
		<div class="num mt-1 text-2xl font-semibold {result.cashAfter < 0 ? 'text-down' : 'text-fg'}">{data.cash == null ? 'Sin dato' : money(result.cashAfter, 2)}</div>
		<div class="text-muted mt-1 text-[11px]">Partes de {money(data.cash, 2)}</div>
	</div>
	<div class="py-3 pl-3">
		<div class="text-muted text-[11px]">Once resultante</div>
		{#if result.after}
			<div class="num mt-1 text-2xl font-semibold">{fixed(result.after.xpts, 1)} <span class="text-sm">pts</span></div>
			<div class="text-muted mt-1 text-[11px]">{result.after.formation}{#if baseline} · <span class={result.after.xpts >= baseline.xpts ? 'text-up' : 'text-down'}>{result.after.xpts >= baseline.xpts ? '+' : '−'}{fixed(Math.abs(result.after.xpts - baseline.xpts), 1)} pts</span>{/if}</div>
		{:else}
			<div class="text-warn mt-1 text-sm font-medium">{result.errors.length ? 'Revisa los importes' : result.missing.length ? 'Aún no hay once' : 'Once viable'}</div>
			<div class="text-muted mt-1 text-[11px]">{result.missing.length ? result.missing.join(' · ') : result.formations.length ? `${result.formations.length} ${result.formations.length === 1 ? 'formación posible' : 'formaciones posibles'} · sin pronóstico de puntos` : 'Sin formación válida'}</div>
		{/if}
	</div>
</div>

{#if changed}
	<div class="border-line mt-3 border-b pb-3 text-xs leading-relaxed">
		<p class="text-muted">Ventas supuestas <span class="num text-fg">{money(result.proceeds, 2)}</span> · compras <span class="num text-fg">{money(result.spent, 2)}</span>.</p>
		{#if data.cash == null}<p class="text-warn mt-1">No hay saldo actualizado: no se puede confirmar si cabe en tu presupuesto.</p>{/if}
		{#if result.cashAfter < 0 && data.cash != null}<p class="text-down mt-1 font-medium">Te faltan {money(-result.cashAfter, 2)} para completar el plan.</p>{/if}
		{#each result.errors as message (message)}<p class="text-down mt-1">{message}</p>{/each}
		{#if result.missing.length}<p class="text-warn mt-1">Para alinear aún te falta {result.missing.join(' y ')}.</p>{/if}
		{#if result.unknown.length && !result.missing.length}<p class="text-warn mt-1">Faltan estimaciones de puntos para {result.unknown.length} {result.unknown.length === 1 ? 'jugador' : 'jugadores'}. Puedes comprobar las formaciones posibles, pero todavía no ordenar el mejor once.</p>{/if}
		{#if !result.after && result.formations.length && !result.missing.length}<p class="text-muted mt-1">Formaciones: {result.formations.join(' · ')}.</p>{/if}
		<button class="text-accent mt-2 min-h-10 text-xs font-semibold" onclick={reset}>Empezar de nuevo</button>
	</div>
{:else}
	<p class="text-muted mt-3 text-xs">Marca jugadores del mercado o de tu plantilla para construir un escenario.</p>
{/if}

{#if result.after && changed}
	<details class="border-line mt-4 border-b pb-3">
		<summary class="text-accent cursor-pointer py-2 text-sm font-semibold">Ver titulares · {result.after.formation} · {fixed(result.after.xpts, 1)} pts</summary>
		<div class="mt-2">
			{#each [1, 2, 3, 4] as pos (pos)}
				<div class="text-muted bg-surface-2/40 px-1 py-1 text-[11px] font-semibold">{pos === 1 ? 'PORTERÍA' : pos === 2 ? 'DEFENSA' : pos === 3 ? 'MEDIOS' : 'DELANTERA'}</div>
				{#each result.after.starters.filter((p) => p.position_id === pos) as p (p.player_id)}
					<div class="border-line flex items-center gap-2 border-b px-1 py-2 text-sm last:border-0">
						<span class="min-w-0 flex-1 truncate">{p.name}{#if buysById.has(p.player_id)} <span class="text-up ml-1 text-[10px] font-semibold">NUEVO</span>{/if}</span>
						<span class="num shrink-0 text-xs">{fixed(p.xpts, 1)} pts</span>
					</div>
				{/each}
			{/each}
			{#if result.before}
				<p class="text-muted mt-3 px-1 text-xs">Entran {result.enters.map((p) => p.name).join(', ') || 'los mismos'}{#if result.exits.length}; salen {result.exits.map((p) => p.name).join(', ')}{/if}.</p>
			{:else}
				<p class="text-up mt-3 px-1 text-xs">Con estas operaciones pasarías de no tener once válido a poder alinear.</p>
			{/if}
		</div>
	</details>
{/if}

<div class="border-line mt-5 grid grid-cols-2 gap-1 border-b pb-2" role="group" aria-label="Operaciones del plan">
	<button type="button" aria-pressed={activeList === 'buys'} onclick={() => activeList = 'buys'} class="min-h-10 rounded-lg px-3 text-sm font-semibold {activeList === 'buys' ? 'bg-surface-2 text-fg' : 'text-muted'}">Fichajes <span class="num text-xs">{buys.length}</span></button>
	<button type="button" aria-pressed={activeList === 'sells'} onclick={() => activeList = 'sells'} class="min-h-10 rounded-lg px-3 text-sm font-semibold {activeList === 'sells' ? 'bg-surface-2 text-fg' : 'text-muted'}">Ventas <span class="num text-xs">{sells.length}</span></button>
</div>

{#if activeList === 'buys'}
<Section title="Fichajes" bare>
	{#snippet aside()}{buys.length} seleccionados{/snippet}
	<div class="flex gap-2 px-1 pb-2">
		<input type="search" bind:value={query} aria-label="Filtrar jugadores del mercado" placeholder="Buscar en el mercado" class="bg-surface border-line min-w-0 flex-1 rounded-lg border px-3 py-2 text-sm outline-none focus:border-accent" />
		<select bind:value={position} aria-label="Filtrar por posición" class="bg-surface border-line rounded-lg border px-2 text-xs">
			<option value={0}>Todas</option><option value={1}>POR</option><option value={2}>DEF</option><option value={3}>MED</option><option value={4}>DEL</option>
		</select>
	</div>
	{#each shownMarket as p (p.player_id)}
		<div class="border-line border-b px-1 py-2.5 last:border-0">
			<div class="flex items-center gap-2">
				<span class="text-muted w-8 shrink-0 text-[10px] font-semibold">{POS[p.position_id]}</span>
				<div class="min-w-0 flex-1">
					<a href="/jugador/{p.player_id}" class="block truncate text-sm font-semibold">{p.name}</a>
					<div class="text-muted truncate text-[11px]">{p.club} · anuncio {money(p.ask)}{#if p.verdict === 'pujar'} · <span class="text-up">puja aconsejada</span>{/if}</div>
				</div>
				<button type="button" aria-pressed={buysById.has(p.player_id)} onclick={() => toggleBuy(p.player_id, p.suggested)} class="min-h-10 shrink-0 rounded-lg px-3 text-xs font-semibold {buysById.has(p.player_id) ? 'bg-accent text-bg' : 'bg-surface-2 text-fg'}">{buysById.has(p.player_id) ? 'Quitar' : 'Añadir'}</button>
			</div>
			{#if buysById.has(p.player_id)}
				<div class="mt-2 flex items-center justify-between gap-2 pl-10 text-xs">
					<label for="buy-{p.player_id}" class="text-muted">Pagaría (M€)</label>
					<input id="buy-{p.player_id}" type="number" inputmode="decimal" min="0" step="0.001" value={buyAmounts[p.player_id]} oninput={(e) => (buyAmounts = { ...buyAmounts, [p.player_id]: e.currentTarget.valueAsNumber })} class="num bg-surface-2 border-line w-28 rounded-lg border px-2 py-2 text-right" />
				</div>
				{#if inEuros(buyAmounts[p.player_id]) < p.ask}<p class="text-down mt-1 pl-10 text-[11px]">Por debajo del precio anunciado.</p>{/if}
				{#if p.max_bid != null && inEuros(buyAmounts[p.player_id]) > p.max_bid}<p class="text-warn mt-1 pl-10 text-[11px]">Supera el máximo rentable individual ({money(p.max_bid)}).</p>{/if}
			{/if}
		</div>
	{:else}
		<p class="text-muted px-1 py-4 text-sm">No hay jugadores con ese filtro.</p>
	{/each}
</Section>

{:else}

<Section title="Ventas" bare>
	{#snippet aside()}{sells.length} seleccionadas{/snippet}
	<p class="text-muted px-1 pb-2 text-xs">El importe inicial es el valor de mercado, no una oferta recibida. Cámbialo por lo que esperas cobrar.</p>
	{#each data.roster as p (p.player_id)}
		<div class="border-line border-b px-1 py-2.5 last:border-0">
			<div class="flex items-center gap-2">
				<span class="text-muted w-8 shrink-0 text-[10px] font-semibold">{POS[p.position_id]}</span>
				<div class="min-w-0 flex-1">
					<a href="/jugador/{p.player_id}" class="block truncate text-sm font-semibold">{p.name}</a>
					<div class="text-muted truncate text-[11px]">{p.club} · valor {money(p.value)}{#if p.unavailable} · no disponible{/if}</div>
				</div>
				<button type="button" aria-pressed={sellersById.has(p.player_id)} onclick={() => toggleSell(p.player_id, p.value)} class="min-h-10 shrink-0 rounded-lg px-3 text-xs font-semibold {sellersById.has(p.player_id) ? 'bg-warn text-bg' : 'bg-surface-2 text-fg'}">{sellersById.has(p.player_id) ? 'Quitar' : 'Vender'}</button>
			</div>
			{#if sellersById.has(p.player_id)}
				<div class="mt-2 flex items-center justify-between gap-2 pl-10 text-xs">
					<label for="sell-{p.player_id}" class="text-muted">Cobraría (M€)</label>
					<input id="sell-{p.player_id}" type="number" inputmode="decimal" min="0" step="0.001" value={sellAmounts[p.player_id]} oninput={(e) => (sellAmounts = { ...sellAmounts, [p.player_id]: e.currentTarget.valueAsNumber })} class="num bg-surface-2 border-line w-28 rounded-lg border px-2 py-2 text-right" />
				</div>
			{/if}
		</div>
	{/each}
</Section>
{/if}

<p class="text-muted border-line mt-5 border-t pt-3 text-xs leading-relaxed">Los puntos son estimaciones para la próxima jornada. Guías de mercado actualizadas {data.recommendationsAt ? relative(data.recommendationsAt) : 'sin fecha disponible'}. Ganar una puja y cobrar una venta no están garantizados; el saldo supone que todas las operaciones seleccionadas se completan.</p>
