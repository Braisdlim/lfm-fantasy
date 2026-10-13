<script lang="ts">
	import PageHeader from '$lib/components/PageHeader.svelte';
	import PlayerAvatar from '$lib/components/PlayerAvatar.svelte';
	import Section from '$lib/components/Section.svelte';
	import { dayText, money, POS, relative, signed } from '$lib/format';
	import type { JournalEntry } from '$lib/server/queries';

	let { data } = $props();
	const s = $derived(data.summary);
	const ENTRY: Record<string, string> = { mercado: 'Del mercado', manager: 'Comprado a un mánager', clausula: 'Clausulado', inicial: 'Plantilla inicial' };
	const EXIT: Record<string, string> = { venta_sistema: 'vendido a LaLiga', venta_manager: 'vendido a un mánager', me_clausularon: 'te lo clausularon' };
	const REC: Record<string, string> = { pujar: 'pujar', no_pujar: 'no pujar', sin_saldo: 'sin saldo', vender: 'vender', aguantar: 'aguantar', sin_datos: 'sin datos' };
	const pct = (x: number | null) => (x == null ? '–' : `${x >= 0 ? '+' : '−'}${Math.abs(x * 100).toFixed(1).replace('.', ',')} %`);
	const tone = (x: number | null) => (x == null ? 'text-muted' : x > 0 ? 'text-up' : x < 0 ? 'text-down' : 'text-muted');
	const linea1 = (e: JournalEntry) => {
		const entrada = [ENTRY[e.entry_kind], e.entry_at ? dayText(e.entry_at) : null].filter(Boolean).join(' ');
		const pago = e.paid != null ? ` · ${money(e.paid)}` : '';
		const salida = e.open
			? `vale ${money(e.value_now)}`
			: `${EXIT[e.exit_kind ?? ''] ?? 'salió'} ${dayText(e.exit_at)}${e.received != null ? ` · ${money(e.received)}` : ''}`;
		return `${entrada}${pago} → ${salida}`;
	};
	const linea2 = (e: JournalEntry) =>
		[
			`${e.points} pts en ${e.weeks} ${e.weeks === 1 ? 'jornada' : 'jornadas'}${e.points_aligned != null ? ` (${e.points_aligned} alineado)` : ''}`,
			e.rec_at_entry ? `al fichar: ${REC[e.rec_at_entry] ?? e.rec_at_entry}` : null,
			e.rec_at_exit ? `al vender: ${REC[e.rec_at_exit] ?? e.rec_at_exit}` : null
		]
			.filter(Boolean)
			.join(' · ');
	const plural = (n: number, uno: string, varios: string) => `${n} ${n === 1 ? uno : varios}`;
	let filtro = $state<'todas' | 'abiertas' | 'cerradas'>('todas');
	const lista = $derived(
		data.entries.filter((e: JournalEntry) => (filtro === 'todas' ? true : filtro === 'abiertas' ? e.open : !e.open))
	);
</script>

<svelte:head><title>lfm · Diario</title></svelte:head>

<PageHeader title="Diario" back="/" />

<p class="text-muted px-1 pt-1 text-xs">
	Las ventas usan lo que cobraste menos lo que pagaste. En los jugadores que aún tienes, la ganancia es potencial: valor actual menos precio pagado. Cada operación se compara con lo que cambió de valor un jugador típico de su posición en las mismas fechas.
	{#if data.computed_at}Actualizado {relative(data.computed_at)}.{/if}
</p>

{#if !data.entries.length}
	<div class="card text-muted mt-4 p-4 text-sm">Aún no hay operaciones. Se calcula en la pasada diaria del job.</div>
{:else}
	<div class="border-line mt-3 grid grid-cols-2 border-y">
		<div class="border-line border-r py-2.5 pr-3">
			<div class="text-muted text-[11px]">Realizado · {plural(s.closedCount, 'cerrada', 'cerradas')}</div>
			<div class="num text-xl {tone(s.realized)}">{signed(s.realized, 2)}</div>
		</div>
		<div class="py-2.5 pl-3">
			<div class="text-muted text-[11px]">Latente · {s.openCount} en plantilla</div>
			<div class="num text-xl {tone(s.unrealized)}">{signed(s.unrealized, 2)}</div>
		</div>
		<div class="border-line border-t border-r py-2.5 pr-3">
			<div class="text-muted text-[11px]">Frente a su posición</div>
			<div class="num text-xl {tone(s.vsBaseline)}">{s.vsBaseline == null ? '–' : signed(s.vsBaseline, 2)}</div>
		</div>
		<div class="border-line border-t py-2.5 pl-3">
			<div class="text-muted text-[11px]">Puntos mientras fueron tuyos</div>
			<div class="num text-xl">{s.points}{#if s.pointsAligned != null}<span class="text-muted text-xs">{` · ${s.pointsAligned} alineados`}</span>{/if}</div>
		</div>
	</div>
	<p class="text-muted mt-2 px-1 text-xs">
		{#if s.buysWithRec}{`De ${plural(s.buysWithRec, 'fichaje', 'fichajes')} con recomendación ese día, el recomendador decía «pujar» en ${s.buysRecommended}. `}{/if}
		{#if s.sellsWithRec}{`De ${plural(s.sellsWithRec, 'venta', 'ventas')}, decía «vender» en ${s.sellsRecommended}. `}{/if}
		«Frente a su posición» son los euros de más o de menos respecto a haber comprado, con el mismo dinero y en las mismas fechas, a un jugador típico de su posición.
	</p>

	<Section title="Operaciones" flush bare>
		{#snippet aside()}
			<span class="flex gap-1">
				{#each [['todas', 'Todas'], ['abiertas', 'En plantilla'], ['cerradas', 'Cerradas']] as [k, l] (k)}
					<button class="chip {filtro === k ? 'bg-accent text-black' : 'bg-surface-2 text-muted'}" onclick={() => (filtro = k as typeof filtro)}>{l}</button>
				{/each}
			</span>
		{/snippet}
		{#each lista as e (e.player_id + (e.entry_at ?? ''))}
			<a href="/jugador/{e.player_id}" class="border-line active:bg-surface-2 flex items-start gap-2.5 border-b px-1 py-2.5 last:border-0">
				<PlayerAvatar image={e.image_url} badge={e.badge_url} name={e.name ?? ''} size="sm" />
				<div class="min-w-0 flex-1">
					<div class="flex items-center gap-1.5">
						<span class="truncate text-sm font-bold">{e.name ?? e.player_id}</span>
						{#if e.position_id}<span class="text-muted text-[10px]">{POS[e.position_id]}</span>{/if}
					</div>
					<div class="text-muted text-[11px]">{linea1(e)}</div>
					<div class="text-muted text-[11px]">{linea2(e)}</div>
				</div>
				<div class="flex w-[5.5rem] shrink-0 flex-col items-end text-right">
					<span class="num text-[15px] font-bold {tone(e.pnl)}">{e.pnl == null ? '–' : signed(e.pnl)}</span>
					<span class="num text-[11px] {tone(e.return)}">{pct(e.return)}</span>
					{#if e.vs_baseline != null}<span class="num text-[10px] {tone(e.vs_baseline)}">{pct(e.vs_baseline)} vs posición</span>{/if}
				</div>
			</a>
		{/each}
	</Section>
{/if}
