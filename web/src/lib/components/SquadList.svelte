<script lang="ts">
	// La lista de plantilla tal como la define el tablero: sin foto, banda por posición, y cada
	// jugador en **dos líneas fijas**. La segunda va con `truncate`, así que da igual cuánto tenga
	// que contar de él: la fila mide siempre lo mismo y caben nueve o diez en pantalla. Antes era
	// una cadena de seis datos separados por puntos que se comía cuatro renglones.
	import Sparkline from './Sparkline.svelte';
	import PlayerAvatar from './PlayerAvatar.svelte';
	import { POS, POS_BADGE, POS_LONG, POS_PLURAL, clauseState, money, playerName, shortClub, signed, STATUS } from '$lib/format';
	import type { SquadPlayer } from '$lib/server/queries';

	let { players, showBuy = true }: { players: SquadPlayer[]; showBuy?: boolean } = $props();

	type Sort = 'valor' | 'subida' | 'semana' | 'puntos' | 'clausula' | 'plusvalia';
	let sort = $state<Sort>('valor');
	let horizon = $state<'value_1d' | 'value_7d' | 'value_30d'>('value_1d');

	const sorted = $derived.by(() => {
		const key = (p: SquadPlayer) => {
			switch (sort) {
				case 'subida':
					return p.value_1d != null ? p.value - p.value_1d : -Infinity;
				case 'semana':
					return p.value_7d != null ? p.value - p.value_7d : -Infinity;
				case 'puntos':
					return p.points_total;
				case 'clausula':
					return p.buyout_clause ?? 0;
				case 'plusvalia':
					return p.bought_for != null ? p.value - p.bought_for : -Infinity;
				default:
					return p.value;
			}
		};
		return [...players].sort((a, b) => key(b) - key(a));
	});
	const groups = $derived(
		sort === 'valor'
			? [1, 2, 3, 4, 5]
					.map((pos) => ({ pos, items: sorted.filter((p) => p.position_id === pos) }))
					.filter((g) => g.items.length)
			: [{ pos: 0, items: sorted }]
	);

	const antes = (p: SquadPlayer) =>
		horizon === 'value_7d' ? p.value_7d : horizon === 'value_30d' ? p.value_30d : p.value_1d;
	const delta = (p: SquadPlayer) => {
		const b = antes(p);
		return b != null ? p.value - b : null;
	};

	/** «Bloq. 6 d» en vez de «Bloqueada en 6 d 12 h»: en una línea que no puede crecer, la unidad
	 *  gruesa basta y lo fino está en la ficha del jugador. */
	const clausula = (p: SquadPlayer) => {
		const st = clauseState(p.clause_locked_until, p.is_shielded);
		if (st.label === 'Blindado') return { cls: st.cls, text: 'Blindado' };
		if (st.open) return { cls: st.cls, text: 'Cláusula abierta' };
		const dias = st.label.match(/(\d+)\s*d/);
		const horas = st.label.match(/(\d+)\s*h/);
		return { cls: st.cls, text: dias ? `Bloq. ${dias[1]} d` : horas ? `Bloq. ${horas[1]} h` : st.label };
	};
</script>

<div class="flex gap-1.5 overflow-x-auto px-1 pb-2.5 text-[11px]">
	{#each [['valor', 'Valor'], ['subida', 'Hoy'], ['semana', '7 d'], ['plusvalia', 'Plusvalía'], ['puntos', 'Puntos'], ['clausula', 'Cláusula']] as [k, label] (k)}
		<button
			class="shrink-0 rounded-md px-2.5 py-1 {sort === k
				? 'bg-fg text-bg font-semibold'
				: 'border-line text-muted border'}"
			onclick={() => (sort = k as Sort)}>{label}</button
		>
	{/each}
</div>

{#each groups as g (g.pos)}
	{#if g.pos}
		<div class="bg-surface border-line text-muted border-y px-1 py-1 text-[10px] font-semibold tracking-[0.08em] uppercase">
			{g.items.length > 1 ? `${POS_PLURAL[g.pos]} · ${g.items.length}` : POS_LONG[g.pos]}
		</div>
	{/if}
	{#each g.items as p (p.player_id)}
		{@const c = clausula(p)}
		{@const plus = p.bought_for != null ? p.value - p.bought_for : null}
		{@const d = delta(p)}
		{@const name = playerName(p)}
		<a
			href="/jugador/{p.player_id}"
			class="border-line active:bg-surface-2 flex items-center gap-2.5 sm:gap-3 border-b px-1 py-2.5 last:border-0"
		>
			<PlayerAvatar image={p.image_url} badge={p.badge_url} {name} size="sm" />
			<div class="min-w-0 flex-1">
				<div class="flex items-center gap-1.5 min-w-0">
					<span class="truncate text-sm font-medium text-fg">{name}</span>
					<span class="rounded px-1.5 py-0.2 text-[9px] font-black uppercase shrink-0 {POS_BADGE[p.position_id]}">
						{POS[p.position_id]}
					</span>
					<span class="text-muted shrink-0 text-[11px] hidden sm:inline">· {shortClub(p.club)}</span>
				</div>
				<div class="mt-0.5 truncate text-[11px]">
					{#if p.status !== 'ok'}<span class={STATUS[p.status]?.cls}>{STATUS[p.status]?.label}</span
						>{' · '}{/if}<span class={c.cls}>{c.text}</span>{#if showBuy && plus != null}<span
							class="text-muted">{' · '}</span
						><span class={plus >= 0 ? 'text-up' : 'text-down'}>{signed(plus)}</span><span class="text-muted"> · pagaste {money(p.bought_for)}</span>{/if}{#if p.next_match}<span
							class="text-muted"
							>{' · '}{p.next_match.home ? 'vs' : 'en'} {shortClub(p.next_match.opponent)}</span
						>{/if}
				</div>
			</div>
			<div class="hidden sm:block shrink-0">
				<Sparkline values={p.spark} width={40} height={18} />
			</div>
			<div class="w-[5.25rem] shrink-0 text-right">
				<div class="num text-[15px] font-medium">{money(p.value)}</div>
				{#if d != null}
					<div class="num mt-0.5 text-[11px] {d >= 0 ? 'text-up' : 'text-down'}">{signed(d)}</div>
				{:else}
					<div class="text-muted mt-0.5 text-[11px]">sin dato</div>
				{/if}
			</div>
		</a>
	{/each}
{/each}

<div class="text-muted mt-2 flex justify-end gap-2 px-1 text-[11px]">
	Variación:
	{#each [['value_1d', '1 d'], ['value_7d', '7 d'], ['value_30d', '30 d']] as [k, label] (k)}
		<button class={horizon === k ? 'text-accent' : ''} onclick={() => (horizon = k as typeof horizon)}
			>{label}</button
		>
	{/each}
</div>
