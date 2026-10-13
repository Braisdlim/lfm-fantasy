<script lang="ts">
	import { goto } from '$app/navigation';
	import { onDestroy } from 'svelte';
	import { createPlayerSearch } from '$lib/player-search';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import {
		money,
		num,
		POS,
		POS_BADGE,
		POS_BORDER,
		shortClub,
		signed,
	} from '$lib/format';

	let { data } = $props();

	const p1 = $derived(data.p1);
	const p2 = $derived(data.p2);

	let searchSlot = $state<1 | 2 | null>(null);
	let searchTerm = $state('');
	let localResults = $state<any[]>([]);
	let isSearching = $state(false);
	let searchError = $state(false);
	const search = createPlayerSearch<any>((state) => {
		localResults = state.results;
		isSearching = state.loading;
		searchError = state.error;
	});
	onDestroy(search.destroy);

	function doSearch(term: string) {
		searchTerm = term;
		search.update(term);
	}

	function closeSearch() {
		search.reset();
		searchSlot = null;
		searchTerm = '';
	}

	function selectPlayer(slot: 1 | 2, id: string) {
		closeSearch();
		const nextP1 = slot === 1 ? id : data.p1Id ?? '';
		const nextP2 = slot === 2 ? id : data.p2Id ?? '';

		const params = new URLSearchParams();
		if (nextP1) params.set('p1', nextP1);
		if (nextP2) params.set('p2', nextP2);
		goto(`/comparar?${params.toString()}`);
	}

	function removePlayer(slot: 1 | 2) {
		const nextP1 = slot === 1 ? '' : data.p1Id ?? '';
		const nextP2 = slot === 2 ? '' : data.p2Id ?? '';

		const params = new URLSearchParams();
		if (nextP1) params.set('p1', nextP1);
		if (nextP2) params.set('p2', nextP2);
		goto(`/comparar?${params.toString()}`);
	}

	// Métricas calculadas para comparar
	const c1 = $derived(p1?.card);
	const c2 = $derived(p2?.card);

	const diff1d_1 = $derived(c1?.value_1d != null ? c1.value - c1.value_1d : null);
	const diff1d_2 = $derived(c2?.value_1d != null ? c2.value - c2.value_1d : null);

	const diff7d_1 = $derived(c1?.value_7d != null ? c1.value - c1.value_7d : null);
	const diff7d_2 = $derived(c2?.value_7d != null ? c2.value - c2.value_7d : null);

	const media1 = $derived(c1?.average_points ?? 0);
	const media2 = $derived(c2?.average_points ?? 0);
	const media1Missing = $derived(c1?.average_points == null);
	const media2Missing = $derived(c2?.average_points == null);

	const pts1 = $derived(c1?.points_total ?? 0);
	const pts2 = $derived(c2?.points_total ?? 0);

	const titular1 = $derived(p1?.availability?.start_prob ?? null);
	const titular2 = $derived(p2?.availability?.start_prob ?? null);

	const pen1 = $derived(p1?.setPieces?.pen_taken ?? null);
	const pen2 = $derived(p2?.setPieces?.pen_taken ?? null);

	const cor1 = $derived(p1?.setPieces?.corner_taken ?? null);
	const cor2 = $derived(p2?.setPieces?.corner_taken ?? null);

	const fk1 = $derived(p1?.setPieces?.fk_taken ?? null);
	const fk2 = $derived(p2?.setPieces?.fk_taken ?? null);
</script>

<svelte:head><title>lfm · Cara a Cara</title></svelte:head>

<PageHeader title="Cara a Cara" back="/mercado">
	Comparativa directa entre dos jugadores
</PageHeader>

<!-- Rejilla de los dos contendientes -->
<div class="mt-2 grid grid-cols-2 gap-2 sm:gap-4 items-stretch">
	<!-- Casilla 1 -->
	<div class="bg-surface border-line relative flex flex-col justify-between rounded-xl border p-3 shadow-xs">
		{#if c1}
			<div class="flex items-start justify-between gap-1">
				<span class="rounded px-1.5 py-0.5 text-[10px] font-black uppercase {POS_BADGE[c1.position_id]}">
					{POS[c1.position_id]}
				</span>
				<button
					onclick={() => removePlayer(1)}
					class="text-muted hover:text-fg text-xs p-1 rounded-md hover:bg-surface-2 transition-colors"
					title="Quitar jugador"
				>
					✕
				</button>
			</div>

			<div class="my-2 flex flex-col items-center text-center">
				<div class="relative">
					{#if c1.image_url}
						<img
							src={c1.image_url}
							alt={c1.nickname ?? c1.name}
							class="h-16 w-16 sm:h-20 sm:w-20 rounded-full border-2 bg-surface-2 object-cover {POS_BORDER[c1.position_id] ?? 'border-line'} shadow-md"
						/>
					{:else}
						<div class="num flex h-16 w-16 sm:h-20 sm:w-20 items-center justify-center rounded-full border-2 bg-surface-2 text-base font-bold text-muted {POS_BORDER[c1.position_id] ?? 'border-line'}">
							{POS[c1.position_id] ?? '?'}
						</div>
					{/if}
					{#if c1.badge_url}
						<img src={c1.badge_url} alt={c1.club} class="absolute -bottom-1 -right-1 h-6 w-6 object-contain drop-shadow" />
					{/if}
				</div>

				<div class="mt-2 font-bold text-sm sm:text-base text-fg truncate max-w-full">
					{c1.nickname ?? c1.name}
				</div>
				<div class="text-muted text-xs">{c1.club}</div>
				<div class="num mt-1 text-sm font-extrabold text-fg">{money(c1.value, 1)}</div>
			</div>

			<a
				href="/jugador/{c1.player_id}"
				class="bg-surface-2 hover:bg-surface-2/80 text-muted hover:text-fg mt-1 block w-full rounded-lg py-1.5 text-center text-xs font-semibold transition-colors"
			>
				Ver ficha →
			</a>
		{:else}
			<div class="flex flex-col items-center justify-center py-8 text-center flex-1">
				<div class="h-12 w-12 rounded-full border-2 border-dashed border-line flex items-center justify-center text-muted text-xl mb-2">
					+
				</div>
				<p class="text-muted text-xs font-medium mb-3">Elige al primer jugador</p>
				<button
					onclick={() => { closeSearch(); searchSlot = 1; }}
					class="bg-accent text-black font-bold rounded-lg px-3 py-1.5 text-xs shadow-xs hover:opacity-90 transition-opacity"
				>
					Seleccionar
				</button>
			</div>
		{/if}
	</div>

	<!-- Casilla 2 -->
	<div class="bg-surface border-line relative flex flex-col justify-between rounded-xl border p-3 shadow-xs">
		{#if c2}
			<div class="flex items-start justify-between gap-1">
				<span class="rounded px-1.5 py-0.5 text-[10px] font-black uppercase {POS_BADGE[c2.position_id]}">
					{POS[c2.position_id]}
				</span>
				<button
					onclick={() => removePlayer(2)}
					class="text-muted hover:text-fg text-xs p-1 rounded-md hover:bg-surface-2 transition-colors"
					title="Quitar jugador"
				>
					✕
				</button>
			</div>

			<div class="my-2 flex flex-col items-center text-center">
				<div class="relative">
					{#if c2.image_url}
						<img
							src={c2.image_url}
							alt={c2.nickname ?? c2.name}
							class="h-16 w-16 sm:h-20 sm:w-20 rounded-full border-2 bg-surface-2 object-cover {POS_BORDER[c2.position_id] ?? 'border-line'} shadow-md"
						/>
					{:else}
						<div class="num flex h-16 w-16 sm:h-20 sm:w-20 items-center justify-center rounded-full border-2 bg-surface-2 text-base font-bold text-muted {POS_BORDER[c2.position_id] ?? 'border-line'}">
							{POS[c2.position_id] ?? '?'}
						</div>
					{/if}
					{#if c2.badge_url}
						<img src={c2.badge_url} alt={c2.club} class="absolute -bottom-1 -right-1 h-6 w-6 object-contain drop-shadow" />
					{/if}
				</div>

				<div class="mt-2 font-bold text-sm sm:text-base text-fg truncate max-w-full">
					{c2.nickname ?? c2.name}
				</div>
				<div class="text-muted text-xs">{c2.club}</div>
				<div class="num mt-1 text-sm font-extrabold text-fg">{money(c2.value, 1)}</div>
			</div>

			<a
				href="/jugador/{c2.player_id}"
				class="bg-surface-2 hover:bg-surface-2/80 text-muted hover:text-fg mt-1 block w-full rounded-lg py-1.5 text-center text-xs font-semibold transition-colors"
			>
				Ver ficha →
			</a>
		{:else}
			<div class="flex flex-col items-center justify-center py-8 text-center flex-1">
				<div class="h-12 w-12 rounded-full border-2 border-dashed border-line flex items-center justify-center text-muted text-xl mb-2">
					+
				</div>
				<p class="text-muted text-xs font-medium mb-3">Elige al rival para comparar</p>
				<button
					onclick={() => { closeSearch(); searchSlot = 2; }}
					class="bg-accent text-black font-bold rounded-lg px-3 py-1.5 text-xs shadow-xs hover:opacity-90 transition-opacity"
				>
					Seleccionar
				</button>
			</div>
		{/if}
	</div>
</div>

<!-- Modal / Selector de búsqueda -->
{#if searchSlot !== null}
	<div class="bg-surface border-line mt-3 rounded-xl border p-3 shadow-lg">
		<div class="flex items-center justify-between pb-2 border-b border-line mb-3">
			<span class="font-bold text-xs text-fg">Buscar jugador para la casilla #{searchSlot}</span>
			<button onclick={closeSearch} class="text-muted hover:text-fg min-h-10 px-2 text-xs">Cerrar</button>
		</div>

		<form
			onsubmit={(e) => {
				e.preventDefault();
				const form = e.currentTarget;
				const input = form.querySelector('input') as HTMLInputElement;
				if (input?.value) doSearch(input.value);
			}}
			class="relative flex items-center"
		>
			<input
				aria-label="Buscar jugador para comparar"
				type="search"
				placeholder="Escribe el nombre del jugador (ej. Yamal, Mbappé, Recio)..."
				class="w-full rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs text-fg placeholder:text-muted focus:border-accent focus:outline-hidden"
				oninput={(e) => doSearch(e.currentTarget.value)}
			/>
		</form>

		<!-- Resultados de búsqueda -->
		{#if isSearching}
			<p class="text-muted p-3 text-center text-xs" role="status">Buscando…</p>
		{:else if searchError}
			<p class="text-warn p-3 text-center text-xs" role="status">No se pudo buscar. Prueba otra vez.</p>
		{:else if localResults.length > 0}
			<div class="divide-line mt-2 max-h-56 divide-y overflow-y-auto rounded-lg border border-line bg-surface">
				{#each localResults as r (r.player_id)}
					<button
						onclick={() => selectPlayer(searchSlot!, r.player_id)}
						class="flex w-full items-center justify-between p-2 text-left hover:bg-surface-2/60 transition-colors"
					>
						<div class="flex items-center gap-2 min-w-0">
							<span class="rounded px-1.5 py-0.5 text-[9px] font-black uppercase {POS_BADGE[r.position_id]}">
								{POS[r.position_id]}
							</span>
							<span class="text-xs font-semibold text-fg truncate">{r.nickname ?? r.name}</span>
							<span class="text-muted text-[11px]">{shortClub(r.club)}</span>
						</div>
						<span class="num text-xs font-bold text-fg shrink-0">{money(r.value, 1)}</span>
					</button>
				{/each}
			</div>
		{:else if searchTerm.trim().length >= 2}
			<p class="text-muted p-3 text-center text-xs">No hay jugadores para «{searchTerm.trim()}».</p>
		{:else}
			<!-- Sugerencias rápidas -->
			<div class="mt-3">
				<div class="text-muted text-[11px] font-semibold uppercase tracking-wider mb-2">
					{c1 && searchSlot === 2 ? `Sugerencias en su posición (${POS[c1.position_id]})` : 'Jugadores destacados'}
				</div>
				<div class="flex flex-wrap gap-1.5">
					{#each data.suggestions as s (s.player_id)}
						<button
							onclick={() => selectPlayer(searchSlot!, s.player_id)}
							class="bg-surface-2 hover:bg-surface-2/80 border border-line rounded-lg px-2.5 py-1 text-xs flex items-center gap-1.5 transition-colors"
						>
							<span class="rounded px-1 py-px text-[9px] font-bold uppercase {POS_BADGE[s.position_id]}">
								{POS[s.position_id]}
							</span>
							<span class="font-medium text-fg">{s.nickname ?? s.name}</span>
							<span class="num text-muted text-[10px]">{money(s.value, 1)}</span>
						</button>
					{/each}
				</div>
			</div>
		{/if}
	</div>
{/if}

<!-- Tabla comparativa si ambos jugadores están seleccionados -->
{#if c1 && c2}
	<!-- Veredicto Sintético -->
	<div class="card bg-surface-2/40 border-line mt-4 p-3 text-xs leading-relaxed">
		<div class="flex items-center gap-1.5 font-bold text-accent mb-1">
			<span>Veredicto del Comparador</span>
		</div>
		<p class="text-fg/90">
			{#if media1Missing || media2Missing}
				Falta la media de puntos de uno de los jugadores. Compara precio, disponibilidad y próximo rival antes de decidir.
			{:else if media1 > media2 && titular1 != null && titular2 != null && titular1 >= titular2}
				<b class="text-fg">{c1.nickname ?? c1.name}</b> presenta una ventaja clara tanto en promedio de puntos (<b class="text-up">{num(media1, 1)}</b> frente a {num(media2, 1)}) como en regularidad en el once ({Math.round(titular1 * 100)} % vs {Math.round(titular2 * 100)} %).
			{:else if media2 > media1 && titular1 != null && titular2 != null && titular2 >= titular1}
				<b class="text-fg">{c2.nickname ?? c2.name}</b> presenta una ventaja clara tanto en promedio de puntos (<b class="text-up">{num(media2, 1)}</b> frente a {num(media1, 1)}) como en regularidad en el once ({Math.round(titular2 * 100)} % vs {Math.round(titular1 * 100)} %).
			{:else if media1 > media2}
				<b class="text-fg">{c1.nickname ?? c1.name}</b> promedia más puntos por partido (+{num(media1 - media2, 1)} pts/j).{#if titular1 != null && titular2 != null} <b class="text-fg">{c2.nickname ?? c2.name}</b> tiene mayor previsión de titularidad ({Math.round(titular2 * 100)} % frente a {Math.round(titular1 * 100)} %).{/if}
			{:else if media2 > media1}
				<b class="text-fg">{c2.nickname ?? c2.name}</b> promedia más puntos por partido (+{num(media2 - media1, 1)} pts/j).{#if titular1 != null && titular2 != null} <b class="text-fg">{c1.nickname ?? c1.name}</b> tiene mayor previsión de titularidad ({Math.round(titular1 * 100)} % frente a {Math.round(titular2 * 100)} %).{/if}
			{:else}
				Ambos jugadores tienen el mismo promedio de puntos. Revisa su precio, disponibilidad y próximo rival.
			{/if}
			{#if pen1 != null && pen1 > 0 && pen2 === 0}
				Además, <b class="text-fg">{c1.nickname ?? c1.name}</b> es el encargado de lanzar los penaltis de su equipo.
			{:else if pen2 != null && pen2 > 0 && pen1 === 0}
				Además, <b class="text-fg">{c2.nickname ?? c2.name}</b> es el encargado de lanzar los penaltis de su equipo.
			{/if}
		</p>
	</div>

	<!-- Tabla de Métricas Cara a Cara -->
	<div class="card mt-3 divide-line divide-y overflow-hidden shadow-sm text-xs">
		<!-- Valor de mercado -->
		<div class="grid grid-cols-3 p-2.5 items-center">
			<div class="text-left font-bold num {c1.value < c2.value ? 'text-up' : 'text-fg'}">
				{money(c1.value, 1)}
				{#if c1.value < c2.value}
					<span class="block text-[10px] text-up font-normal">Más barato ({money(c2.value - c1.value, 1)} menos)</span>
				{/if}
			</div>
			<div class="text-center text-muted font-medium text-[11px]">Valor de mercado</div>
			<div class="text-right font-bold num {c2.value < c1.value ? 'text-up' : 'text-fg'}">
				{money(c2.value, 1)}
				{#if c2.value < c1.value}
					<span class="block text-[10px] text-up font-normal">Más barato ({money(c1.value - c2.value, 1)} menos)</span>
				{/if}
			</div>
		</div>

		<!-- Tendencia hoy -->
		<div class="grid grid-cols-3 p-2.5 items-center">
			<div class="text-left font-bold num {diff1d_1 == null ? 'text-muted' : diff1d_1 > 0 ? 'text-up' : diff1d_1 < 0 ? 'text-down' : 'text-muted'}">
				{diff1d_1 == null ? 'Sin dato' : signed(diff1d_1, 1)}
			</div>
			<div class="text-center text-muted font-medium text-[11px]">Subida hoy</div>
			<div class="text-right font-bold num {diff1d_2 == null ? 'text-muted' : diff1d_2 > 0 ? 'text-up' : diff1d_2 < 0 ? 'text-down' : 'text-muted'}">
				{diff1d_2 == null ? 'Sin dato' : signed(diff1d_2, 1)}
			</div>
		</div>

		<!-- Tendencia 7 días -->
		<div class="grid grid-cols-3 p-2.5 items-center">
			<div class="text-left font-bold num {diff7d_1 == null ? 'text-muted' : diff7d_1 > 0 ? 'text-up' : diff7d_1 < 0 ? 'text-down' : 'text-muted'}">
				{diff7d_1 == null ? 'Sin dato' : signed(diff7d_1, 1)}
			</div>
			<div class="text-center text-muted font-medium text-[11px]">Últimos 7 días</div>
			<div class="text-right font-bold num {diff7d_2 == null ? 'text-muted' : diff7d_2 > 0 ? 'text-up' : diff7d_2 < 0 ? 'text-down' : 'text-muted'}">
				{diff7d_2 == null ? 'Sin dato' : signed(diff7d_2, 1)}
			</div>
		</div>

		<!-- Media de puntos -->
		<div class="grid grid-cols-3 p-2.5 items-center bg-surface-2/20">
			<div class="text-left font-extrabold text-sm num {!media1Missing && !media2Missing && media1 >= media2 ? 'text-up' : 'text-fg'}">
				{media1Missing ? 'Sin dato' : `${num(media1, 1)} pts`}
				{#if !media1Missing && !media2Missing && media1 > media2}
					<span class="text-[10px] text-up font-bold">★</span>
				{/if}
			</div>
			<div class="text-center text-fg font-bold text-[11px]">Media / Jornada</div>
			<div class="text-right font-extrabold text-sm num {!media1Missing && !media2Missing && media2 >= media1 ? 'text-up' : 'text-fg'}">
				{#if !media1Missing && !media2Missing && media2 > media1}
					<span class="text-[10px] text-up font-bold">★</span>
				{/if}
				{media2Missing ? 'Sin dato' : `${num(media2, 1)} pts`}
			</div>
		</div>

		<!-- Puntos totales -->
		<div class="grid grid-cols-3 p-2.5 items-center">
			<div class="text-left font-bold num {pts1 >= pts2 ? 'text-up' : 'text-fg'}">
				{pts1} pts
			</div>
			<div class="text-center text-muted font-medium text-[11px]">Puntos totales</div>
			<div class="text-right font-bold num {pts2 >= pts1 ? 'text-up' : 'text-fg'}">
				{pts2} pts
			</div>
		</div>

		<!-- Probabilidad de titularidad -->
		<div class="grid grid-cols-3 p-2.5 items-center">
			<div class="text-left font-bold num {titular1 == null ? 'text-muted' : titular1 >= 0.7 ? 'text-up' : 'text-warn'}">
				{titular1 == null ? 'Sin dato' : `${Math.round(titular1 * 100)} %`}
			</div>
			<div class="text-center text-muted font-medium text-[11px]">Titularidad</div>
			<div class="text-right font-bold num {titular2 == null ? 'text-muted' : titular2 >= 0.7 ? 'text-up' : 'text-warn'}">
				{titular2 == null ? 'Sin dato' : `${Math.round(titular2 * 100)} %`}
			</div>
		</div>

		<!-- Balón parado: Penaltis -->
		<div class="grid grid-cols-3 p-2.5 items-center">
			<div class="text-left font-bold num {pen1 != null && pen1 > 0 ? 'text-up' : 'text-muted'}">
				{pen1 == null ? 'Sin dato' : `${pen1} penalti${pen1 === 1 ? '' : 's'}`}
			</div>
			<div class="text-center text-muted font-medium text-[11px]">Penaltis</div>
			<div class="text-right font-bold num {pen2 != null && pen2 > 0 ? 'text-up' : 'text-muted'}">
				{pen2 == null ? 'Sin dato' : `${pen2} penalti${pen2 === 1 ? '' : 's'}`}
			</div>
		</div>

		<!-- Balón parado: Córners y faltas -->
		<div class="grid grid-cols-3 p-2.5 items-center">
			<div class="text-left font-medium num text-fg">
				{cor1 == null || fk1 == null ? 'Sin dato' : `${cor1} · ${fk1}`}
			</div>
			<div class="text-center text-muted font-medium text-[11px]">Córners · Faltas</div>
			<div class="text-right font-medium num text-fg">
				{cor2 == null || fk2 == null ? 'Sin dato' : `${cor2} · ${fk2}`}
			</div>
		</div>

		<!-- Próximo rival -->
		<div class="grid grid-cols-3 p-2.5 items-center">
			<div class="text-left text-fg font-medium">
				{#if c1.next_match}
					<span class="font-bold">{c1.next_match.home ? '(C)' : '(F)'}</span> {shortClub(c1.next_match.opponent)}
				{:else}
					–
				{/if}
			</div>
			<div class="text-center text-muted font-medium text-[11px]">Próximo partido</div>
			<div class="text-right text-fg font-medium">
				{#if c2.next_match}
					<span class="font-bold">{c2.next_match.home ? '(C)' : '(F)'}</span> {shortClub(c2.next_match.opponent)}
				{:else}
					–
				{/if}
			</div>
		</div>

		<!-- Estado en tu liga -->
		<div class="grid grid-cols-3 p-2.5 items-center bg-surface-2/10">
			<div class="text-left text-[11px]">
				{#if p1?.owner?.is_me}
					<span class="text-accent font-bold">✓ En tu plantilla</span>
				{:else if p1?.onSale}
					<span class="text-amber-400 font-bold">En mercado</span>
				{:else if p1?.owner?.manager_name}
					<span class="text-muted truncate block max-w-[100px]">de {p1.owner.manager_name}</span>
				{:else}
					<span class="text-muted">Libre</span>
				{/if}
			</div>
			<div class="text-center text-muted font-medium text-[11px]">En tu liga</div>
			<div class="text-right text-[11px]">
				{#if p2?.owner?.is_me}
					<span class="text-accent font-bold">✓ En tu plantilla</span>
				{:else if p2?.onSale}
					<span class="text-amber-400 font-bold">En mercado</span>
				{:else if p2?.owner?.manager_name}
					<span class="text-muted truncate block max-w-[100px]">de {p2.owner.manager_name}</span>
				{:else}
					<span class="text-muted">Libre</span>
				{/if}
			</div>
		</div>
	</div>
{/if}
