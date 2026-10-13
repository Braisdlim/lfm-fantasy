<script lang="ts">
	import { onDestroy, untrack } from 'svelte';
	import { goto } from '$app/navigation';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import PlayerRow from '$lib/components/PlayerRow.svelte';
	import PlayerAvatar from '$lib/components/PlayerAvatar.svelte';
	import { POS, STATUS, money } from '$lib/format';
	import { createPlayerSearch } from '$lib/player-search';
	import type { PlayerCard } from '$lib/server/queries';
	import type { Snapshot } from './$types';
	let { data } = $props();
	let term = $state(untrack(() => data.q));
	let live = $state(false);
	let results = $state<PlayerCard[]>([]);
	let loading = $state(false);
	let error = $state(false);
	let input: HTMLInputElement;
	let matches = $state<HTMLUListElement>();
	const search = createPlayerSearch<PlayerCard>((state) => {
		results = state.results; loading = state.loading; error = state.error;
	});
	$effect(() => { term = data.q; live = false; search.reset(); });
	onDestroy(search.destroy);
	function update() {
		live = true;
		search.update(term, data.pos);
		if (!term.trim() && data.q) goto(buildUrl(), { replaceState: true, keepFocus: true, noScroll: true });
	}
	function dismiss() { term = data.q; live = false; search.reset(); }
	export const snapshot: Snapshot<{ term: string; live: boolean }> = {
		capture: () => ({ term, live }),
		restore: (saved) => { term = saved.term; live = saved.live; if (live) search.update(term, data.pos); }
	};
	function buildUrl(params: { pos?: number; sort?: string } = {}) {
		const sp = new URLSearchParams();
		if (term.trim()) sp.set('q', term.trim());
		const pos = params.pos ?? data.pos;
		const sort = params.sort ?? data.sort;
		if (pos) sp.set('pos', String(pos));
		if (sort !== 'valor') sp.set('sort', sort);
		return `/buscar${sp.size ? `?${sp}` : ''}`;
	}
	function focusMatch(event: KeyboardEvent) {
		if (event.key === 'ArrowDown' && matches) { event.preventDefault(); matches.querySelector('a')?.focus(); }
		if (event.key === 'Escape') dismiss();
	}
</script>

<svelte:head><title>lfm · Buscar jugadores</title></svelte:head>
<PageHeader title="Buscar" fresh={data.fresh} />
<p class="text-muted mt-1 text-sm">Encuentra un jugador y abre su ficha.</p>

<form method="GET" class="mt-5" data-sveltekit-keepfocus data-sveltekit-replacestate>
	<label for="player-search" class="mb-2 block text-sm font-medium">Nombre o apodo</label>
	<div class="flex gap-2">
		<div class="relative min-w-0 flex-1">
			<input bind:this={input} id="player-search" name="q" bind:value={term} oninput={(event) => { term = event.currentTarget.value; update(); }} onkeydown={focusMatch}
				type="search" placeholder="Ej. Lamine, Vinicius…" autocomplete="off" aria-describedby="search-help"
				class="bg-surface border-line focus:border-accent min-h-12 w-full rounded-xl border py-3 pr-3 pl-10 text-base" />
			<svg aria-hidden="true" class="text-muted pointer-events-none absolute top-4 left-3.5 size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" /></svg>
		</div>
		<button class="bg-accent text-bg min-h-12 rounded-xl px-4 text-sm font-semibold" type="submit">Buscar</button>
	</div>
	<p id="search-help" class="text-muted mt-2 text-xs">Escribe al menos 2 letras para ver coincidencias.</p>
	{#if data.pos}<input type="hidden" name="pos" value={data.pos} />{/if}
	{#if data.sort !== 'valor'}<input type="hidden" name="sort" value={data.sort} />{/if}
</form>

{#if live && term.trim().length >= 2}
	<section aria-label="Coincidencias" class="border-line mt-5 border-y py-1">
		<div class="flex min-h-11 items-center justify-between gap-2">
			<h2 class="text-sm font-semibold">Coincidencias</h2>
			<span class="text-muted text-xs" role="status">{loading ? 'Buscando…' : error ? 'No se pudo buscar' : results.length === 1 ? '1 coincidencia' : `${results.length > 8 ? 'Primeras 8' : results.length} coincidencias`}</span>
		</div>
		{#if error}
			<p class="text-muted py-2 text-sm">No pudimos cargar los jugadores. Vuelve a intentarlo.</p>
			<button onclick={update} class="text-accent min-h-11 text-sm font-semibold">Reintentar</button>
		{:else if !loading && !results.length}
			<p class="text-muted py-4 text-sm">Sin coincidencias. Prueba otro nombre{data.pos ? ' o cambia la posición seleccionada' : ' o apodo'}.</p>
		{:else}
			<ul bind:this={matches} class="divide-line divide-y" aria-label="Jugadores encontrados">
				{#each results.slice(0, 8) as p (p.player_id)}
					<li><a href="/jugador/{p.player_id}" class="hover:bg-surface-2 flex min-h-16 items-center gap-3 rounded-lg px-2 py-3"
						onkeydown={(event) => {
							const links = [...(matches?.querySelectorAll('a') ?? [])];
							const index = links.indexOf(event.currentTarget);
							if (event.key === 'ArrowDown') { event.preventDefault(); links[Math.min(index + 1, links.length - 1)]?.focus(); }
							if (event.key === 'ArrowUp') { event.preventDefault(); if (index === 0) input.focus(); else links[index - 1]?.focus(); }
							if (event.key === 'Escape') { dismiss(); input.focus(); }
						}}>
						<PlayerAvatar image={p.image_url} name={p.nickname ?? p.name} />
						<span class="min-w-0 flex-1"><span class="block truncate text-sm font-semibold">{p.nickname ?? p.name}</span><span class="text-muted block text-xs">{p.club} · {POS[p.position_id ?? 0]}</span></span>
						<span class="num shrink-0 text-sm">{money(p.value, 1)}</span>
						<svg aria-hidden="true" class="text-muted size-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="m9 5 7 7-7 7" /></svg>
					</a></li>
				{/each}
			</ul>
			{#if !loading && results.length}<a class="text-accent flex min-h-11 items-center justify-center text-sm font-semibold" href={buildUrl()}>Ver más resultados y ordenar</a>{/if}
		{/if}
	</section>
{/if}

<nav aria-label="Posición del jugador" class="mt-5 flex flex-wrap gap-1.5">
	{#each [[0, 'Todas'], [1, 'Porteros'], [2, 'Defensas'], [3, 'Medios'], [4, 'Delanteros']] as [id, label] (id)}
		<a href={buildUrl({ pos: id as number })} data-sveltekit-replacestate aria-current={data.pos === id ? 'true' : undefined}
			class="flex min-h-11 items-center rounded-lg px-3 text-xs font-medium {data.pos === id ? 'bg-fg text-bg' : 'bg-surface-2 text-muted hover:text-fg'}">{label}</a>
	{/each}
</nav>

{#if !live || !term.trim()}
	<div class="mt-5 flex flex-wrap items-center justify-between gap-2">
		<h2 class="text-sm font-semibold">{data.q ? 'Resultados' : 'Explorar jugadores'}</h2>
		<label class="text-muted flex min-h-11 items-center gap-2 text-xs">Ordenar por
			<select aria-label="Ordenar jugadores" value={data.sort} onchange={(event) => goto(buildUrl({ sort: event.currentTarget.value }), { replaceState: true, keepFocus: true, noScroll: true })} class="bg-surface border-line text-fg min-h-11 rounded-lg border px-2 text-sm">
				<option value="valor">Valor</option><option value="puntos">Puntos</option><option value="subida">Suben hoy</option>
			</select>
		</label>
	</div>
	<p class="text-muted mt-1 text-xs">{data.results.length === 40 ? 'Mostrando los primeros 40 jugadores. Busca por nombre para afinar.' : `${data.results.length} ${data.results.length === 1 ? 'jugador' : 'jugadores'}`}</p>
	<div class="card mt-3 divide-line divide-y overflow-hidden">
		{#each data.results as p (p.player_id)}
			<PlayerRow {p}>{#snippet sub()}<span class={STATUS[p.status]?.cls}>{STATUS[p.status]?.label ?? p.status}</span> · {p.points_total} pts{/snippet}</PlayerRow>
		{:else}<p class="text-muted p-5 text-sm">Sin resultados. Prueba otro nombre o selecciona Todas las posiciones.</p>{/each}
	</div>
{/if}
