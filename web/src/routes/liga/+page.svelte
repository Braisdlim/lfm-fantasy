<script lang="ts">
	import { page } from '$app/state';
	import { replaceState } from '$app/navigation';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import PlayerRow from '$lib/components/PlayerRow.svelte';
	import RivalCard from '$lib/components/RivalCard.svelte';
	import Section from '$lib/components/Section.svelte';
	import { ACTIVITY, clauseState, clauseVsValue, money, relative, signed } from '$lib/format';
	let { data } = $props();
	type Filter = 'alcance' | 'abiertas' | 'pronto' | 'regaladas' | 'todas';
	const params = $derived(new URLSearchParams(page.state.leagueFilters ?? page.url.search));
	const filter = $derived((['alcance', 'abiertas', 'pronto', 'regaladas', 'todas'].includes(params.get('clausulas') ?? '') ? params.get('clausulas') : 'alcance') as Filter);
	const position = $derived(Number(params.get('pos')) || 0);
	const price = $derived(params.get('precio') ?? 'all');
	const sort = $derived(params.get('orden') ?? 'chollo');
	function setFilter(key: string, value: string) {
		const url = new URL(window.location.href);
		url.searchParams.set(key, value);
		replaceState(url, { ...page.state, leagueFilters: url.search });
	}
	const now = Date.now();
	const money_ = $derived(data.team?.team_money ?? 0);
	const rivals = $derived(data.clauses.filter((c) => !c.owner_is_me && c.status !== 'out_of_league'));
	const rows = $derived.by(() => {
		const open = (c: (typeof rivals)[number]) => clauseState(c.clause_locked_until, c.is_shielded, now).open;
		const soon = (c: (typeof rivals)[number]) => !open(c) && !c.is_shielded && c.clause_locked_until != null && new Date(c.clause_locked_until).getTime() - now < 72 * 36e5;
		let r = rivals;
		if (filter === 'abiertas') r = r.filter(open);
		else if (filter === 'pronto') r = r.filter(soon);
		else if (filter === 'regaladas') r = r.filter((c) => c.gap > 0);
		else if (filter === 'alcance') r = r.filter((c) => c.buyout_clause <= money_ && (open(c) || soon(c)));
		if (position) r = r.filter((c) => c.position_id === position);
		const ranges: Record<string, [number, number]> = { all: [0, Infinity], low: [0, 5e6], mid: [5e6, 15e6], high: [15e6, 30e6], premium: [30e6, Infinity] };
		const [min, max] = ranges[price] ?? ranges.all;
		r = r.filter((c) => c.buyout_clause >= min && c.buyout_clause < max);
		return [...r].sort((a, b) => sort === 'barata' ? a.buyout_clause - b.buyout_clause : sort === 'cara' ? b.buyout_clause - a.buyout_clause : b.gap - a.gap).slice(0, 60);
	});
	const richest = $derived([...data.table].filter((r) => !r.is_me && r.cash_estimate != null).sort((a, b) => b.cash_estimate! - a.cash_estimate!)[0]);
</script>

<svelte:head><title>lfm · Liga</title></svelte:head>

<PageHeader title="Liga" fresh={data.fresh} shows="plantilla" />

<nav aria-label="Secciones de Liga" class="mt-3 flex flex-wrap gap-1 text-xs">
	{#each [['clasificacion', 'Clasificación'], ['rivales', 'Rivales'], ['clausulas', 'Cláusulas'], ['actividad', 'Actividad']] as [id, label]}
		<a href="#{id}" class="bg-surface-2 text-muted hover:text-fg flex min-h-11 items-center rounded-lg px-3">{label}</a>
	{/each}
</nav>
<div id="clasificacion" class="mt-4 scroll-mt-4">
	<h2 class="mb-3 text-base font-semibold">Clasificación</h2>
	<div class="divide-line divide-y sm:hidden">
		{#each data.table as r (r.team_id)}
			<details class="py-1 {r.is_me ? 'bg-accent/10 rounded-lg px-3' : 'px-1'}">
				<summary class="cursor-pointer py-3 marker:text-muted">
					<span class="inline-flex w-[calc(100%-1.25rem)] items-baseline justify-between gap-3 align-top">
						<span class="min-w-0"><span class="block break-words text-sm font-semibold">{r.position}. {r.manager_name}{r.is_me ? ' · Tú' : ''}</span>
							<span class="text-muted mt-1 block text-xs">{r.is_me ? 'Saldo' : 'Saldo aprox.'} <span class="num">{r.cash_estimate == null ? 'Sin dato' : `${r.is_me ? '' : '≈'}${money(r.cash_estimate)}`}</span></span>
						</span>
						<span class="num shrink-0 text-sm font-semibold">{r.points} <span class="text-muted font-normal">pts</span></span>
					</span>
				</summary>
				<div class="text-muted space-y-2 pb-3 pl-4 text-sm">
					<p>Valor de plantilla: <span class="num text-fg">{money(r.team_value)}</span></p>
					<p>{r.open_clauses ?? 0} cláusulas abiertas</p>
					{#if !r.is_me && r.clause_spend_observed}<p>Gasto observado en subir cláusulas: {money(r.clause_spend_observed)}</p>{/if}
					<a href="/liga/{r.team_id}" class="text-accent flex min-h-11 items-center font-medium">Ver plantilla →</a>
				</div>
			</details>
		{/each}
	</div>
</div>
<div class="card mt-3 hidden overflow-hidden sm:block">
	<table class="w-full text-sm">
		<thead class="text-muted text-xs">
			<tr>
				<th class="px-3 py-2 text-left font-medium">Manager</th>
				<th class="py-2 text-right font-medium">Pts</th>
				<th class="py-2 text-right font-medium">Saldo</th>
				<th class="py-2 pr-3 text-right font-medium">Valor</th>
			</tr>
		</thead>
		<tbody>
			{#each data.table as r (r.team_id)}
				<tr class="border-line border-t {r.is_me ? 'bg-accent/10' : ''}">
					<!-- A 375 px las cuatro columnas no caben en una línea: «308,3 M» y «103,2 M» se partían
					     en dos renglones. El nombre se trunca y las cifras no se rompen nunca; el número de
					     cláusulas abiertas pasa debajo, donde no le quita ancho a nadie. -->
					<td class="w-full max-w-0 px-3 py-2">
						<a href="/liga/{r.team_id}" class="block">
							<span class="flex items-center gap-1.5">
								<span class="num text-muted w-4 shrink-0 text-right">{r.position}</span>
								<span class="truncate font-medium">{r.manager_name}</span>
								{#if r.previous_position && r.previous_position !== r.position}
									<span class="shrink-0 text-xs {r.previous_position > r.position ? 'text-up' : 'text-down'}">{r.previous_position > r.position ? '▲' : '▼'}</span>
								{/if}
							</span>
							{#if r.open_clauses}
								<span class="text-down ml-[1.375rem] block text-[11px]">{r.open_clauses} cláusulas abiertas</span>
							{/if}
						</a>
					</td>
					<td class="num py-2 text-right font-semibold whitespace-nowrap">{r.points}</td>
					<td class="num py-2 pl-2 text-right whitespace-nowrap">
						{#if r.cash_estimate != null}
							<span class={r.is_me ? '' : 'text-warn'}>{r.is_me ? money(r.cash_estimate) : `≈${money(r.cash_estimate)}`}</span>
							{#if !r.is_me && r.clause_spend_observed}
								<span class="text-muted block text-[10px]">−{money(r.clause_spend_observed)} en cláusulas</span>
							{/if}
						{:else}–{/if}
					</td>
					<td class="num py-2 pr-3 pl-2 text-right whitespace-nowrap">{money(r.team_value)}</td>
				</tr>
			{/each}
		</tbody>
	</table>
</div>
<details class="text-muted mt-3 text-sm"><summary class="min-h-11 cursor-pointer py-3">Saldos rivales aproximados · Cómo se calculan</summary><p class="pb-3 leading-relaxed">
	El saldo rival suma cobros y pagos reales y descuenta las subidas manuales de cláusula que hemos podido detectar desde el 8 de septiembre. Las subidas de valor aumentan «Valor»; solo entran en «Saldo» al vender.
	Faltan las cláusulas anteriores a esa fecha y posibles compensaciones iniciales, así que la cifra sigue siendo aproximada. La diferencia con tu saldo real es {money(data.table.find((r) => !r.is_me)?.cash_uncertainty ?? 0)}; la de cada rival puede ser distinta.
	{#if richest}<strong>{richest.manager_name}</strong> tiene el saldo estimado más alto.{/if}
</p></details>

{#if data.radar.length}
	<Section id="rivales" title="Radar de rivales" flush bare>
		{#snippet aside()}{data.radar.filter((r) => !r.can_field).length ? `${data.radar.filter((r) => !r.can_field).length} con huecos` : 'todos completos'} · {relative(data.radar[0].computed_at)}{/snippet}
		{#each data.radar as r (r.team_id)}<RivalCard {r} />{/each}
		<p class="text-muted px-3 pt-1 text-[11px]">Huecos con sus jugadores disponibles (sin lesionados ni sancionados). «Podría disputarte» cruza lo que le falta con los jugadores de la liga en el mercado a los que llega su saldo estimado.</p>
	</Section>
{/if}

{#if data.threats.some((t) => t.threats.length)}
	<Section title="Quién podría clausularte" flush bare>
		{#snippet aside()}saldo estimado de rivales{/snippet}
		{#each data.threats.filter((t) => t.threats.length) as t (t.player_id)}
			{@const st = clauseState(t.clause_locked_until, t.is_shielded, now)}
			{@const g = clauseVsValue(t.value - t.buyout_clause, 'rival', t.value)}
			<!-- La frase va a lo ancho y no en una columna de 6 rem, donde «a un rival le cuesta
			     4,2 M de más» se partía en tres renglones. -->
			<div class="px-3 py-2.5">
				<div class="flex items-baseline gap-2">
					<a href="/jugador/{t.player_id}" class="min-w-0 flex-1 truncate font-medium">{t.nickname ?? t.name}</a>
					<span class="num shrink-0 text-sm font-semibold">{money(t.buyout_clause)}</span>
				</div>
				<div class="text-muted mt-0.5 text-xs">
					<span class={st.cls}>{st.label}</span>{' · '}<span class={g.cls}>{g.text}</span>
				</div>
				<div class="text-xs {st.open ? 'text-down' : 'text-warn'}">
					{t.threats.length === 1 ? 'Podría pagarla' : 'Podrían pagarla'}: {t.threats
						.map((x) => x.manager_name)
						.join(', ')}
				</div>
			</div>
		{/each}
	</Section>
{/if}

<Section id="clausulas" title="Cláusulas de los rivales" flush bare>
	{#snippet aside()}tu saldo {money(money_)}{/snippet}
	<div class="flex flex-wrap gap-2 py-2 text-xs">
		{#each [['alcance', 'A tu alcance'], ['abiertas', 'Abiertas'], ['pronto', 'Se abren en 72 h'], ['regaladas', 'Por debajo del valor'], ['todas', 'Todas']] as [k, label] (k)}
			<button aria-pressed={filter === k} class="min-h-11 rounded-lg px-3 {filter === k ? 'bg-accent text-black' : 'bg-surface-2 text-muted'}" onclick={() => setFilter('clausulas', k)}>{label}</button>
		{/each}
	</div>
	<details class="text-muted mb-3 text-sm">
		<summary class="min-h-11 cursor-pointer py-3">Precio, posición y orden{position || price !== 'all' || sort !== 'chollo' ? ' · filtros activos' : ''}</summary>
		<div class="grid gap-3 pb-3 sm:grid-cols-3">
			<label>Precio<select value={price} onchange={(e) => setFilter('precio', e.currentTarget.value)} class="bg-surface border-line text-fg mt-1 block min-h-11 w-full rounded-lg border px-3"><option value="all">Todos</option><option value="low">Menos de 5 M</option><option value="mid">5–15 M</option><option value="high">15–30 M</option><option value="premium">Más de 30 M</option></select></label>
			<label>Posición<select value={position} onchange={(e) => setFilter('pos', e.currentTarget.value)} class="bg-surface border-line text-fg mt-1 block min-h-11 w-full rounded-lg border px-3"><option value={0}>Todas</option><option value={1}>Porteros</option><option value={2}>Defensas</option><option value={3}>Medios</option><option value={4}>Delanteros</option></select></label>
			<label>Ordenar por<select value={sort} onchange={(e) => setFilter('orden', e.currentTarget.value)} class="bg-surface border-line text-fg mt-1 block min-h-11 w-full rounded-lg border px-3"><option value="chollo">Mejor precio</option><option value="barata">Más baratas</option><option value="cara">Más caras</option></select></label>
		</div>
	</details>
	{#each rows as c (c.player_id)}
		{@const st = clauseState(c.clause_locked_until, c.is_shielded, now)}
		<PlayerRow p={c}>
			{#snippet sub()}de {c.owner} · <span class={st.cls}>{st.label}</span>{/snippet}
			{#snippet right()}
				<span class="num font-semibold {c.buyout_clause > money_ ? 'text-muted' : ''}">{money(c.buyout_clause)}</span>
				{@const g = clauseVsValue(c.gap, 'yo', c.value)}
				<span class="text-right text-[10px] leading-tight {g.cls}">{g.text}</span>
			{/snippet}
		</PlayerRow>
	{:else}
		<p class="text-muted p-3 text-sm">Nada con este filtro.</p>
	{/each}
</Section>

<Section id="actividad" title="Actividad de la liga" flush bare>
	<ul class="divide-line divide-y text-sm">
		{#each data.feed as a (a.activity_id)}
			<li class="flex items-start gap-2 px-3 py-2">
				<span class="text-muted w-14 shrink-0 text-xs">{relative(a.happened_at)}</span>
				<span class="min-w-0 flex-1">
					<span class="font-medium {a.manager_is_me ? 'text-accent' : ''}">{a.manager ?? '?'}</span>
					{ACTIVITY[a.activity_type] ?? `tipo ${a.activity_type}`}
					{#if a.player_id}<a href="/jugador/{a.player_id}" class="font-medium">{a.player}</a>{/if}
					{#if a.activity_type === 1 && a.manager2}<span class="text-muted"> (de {a.manager2})</span>{/if}
					{#if a.week}<span class="text-muted"> J{a.week}</span>{/if}
				</span>
				{#if a.amount}<span class="num shrink-0 {a.activity_type === 33 || a.activity_type === 6 ? 'text-up' : 'text-down'}">{a.activity_type === 33 || a.activity_type === 6 ? '+' : '−'}{money(a.amount)}</span>{/if}
			</li>
		{/each}
	</ul>
</Section>
