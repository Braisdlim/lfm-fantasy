<script lang="ts">
	import PlayerRow from './PlayerRow.svelte';
	import { num } from '$lib/format';
	import type { SellDecision, SquadSellAdvisorResult } from '$lib/server/queries';

	// Semáforo de ventas, en el mismo lenguaje que Hoy: filetes, un punto de color y la cifra a la
	// derecha. Las tarjetas con marco, degradado y emojis de la primera versión competían entre sí
	// y hacían que esta pantalla pareciera de otra app.
	let { advisor }: { advisor: SquadSellAdvisorResult } = $props();

	type Filter = 'all' | SellDecision;
	let filter = $state<Filter>('all');
	let open = $state<string | null>(null);

	const list = $derived(filter === 'all' ? advisor.players : advisor.players.filter((p) => p.decision === filter));

	const TONE: Record<SellDecision, { dot: string; txt: string; label: string }> = {
		urgent: { dot: 'bg-down', txt: 'text-down', label: 'Véndelo' },
		recommended: { dot: 'bg-warn', txt: 'text-warn', label: 'Valóralo' },
		keep: { dot: 'bg-up', txt: 'text-up', label: 'Mantener' }
	};
	const SEV: Record<string, string> = { high: 'bg-down', medium: 'bg-warn', positive: 'bg-up' };

	const filters: [Filter, string, number][] = $derived([
		['all', 'Todos', advisor.players.length],
		['urgent', 'Vender', advisor.urgentCount],
		['recommended', 'Valorar', advisor.recommendedCount],
		['keep', 'Mantener', advisor.keepCount]
	]);
</script>

{#if advisor.deficitWarning}
	<div class="alert mt-3 rounded-xl px-3.5 py-3 text-xs leading-relaxed">
		<div class="text-fg flex items-center gap-2 font-semibold">
			<span class="bg-down size-2 rounded-full"></span>No puedes alinear un once completo
		</div>
		<p class="text-muted mt-1">{advisor.deficitWarning}</p>
		{#if !advisor.hasGoalkeeper}
			<a href="/mercado?ver=recomendado&pos=1" class="text-accent mt-2 inline-block font-semibold">Ver porteros en el mercado →</a>
		{/if}
	</div>
{/if}

<p class="text-muted mt-3 px-1 text-xs leading-relaxed">
	Decide el recomendador (el mismo del mercado, contrastado hacia atrás) y dos reglas sin predicción: nunca se vende
	a quien necesitas para alinear, y un lesionado o sancionado que no está en tu once se puede vender sin perder puntos.
	Las señales de cada jugador son contexto, no deciden.
</p>

<div class="bg-surface-2 mt-3 flex gap-1 rounded-xl p-1 text-xs">
	{#each filters as [k, label, n] (k)}
		<button
			type="button"
			onclick={() => (filter = k)}
			class="flex-1 rounded-lg px-2 py-1.5 transition-colors {filter === k ? 'bg-surface text-fg font-semibold shadow-xs' : 'text-muted hover:text-fg'}"
		>
			{label}<span class="num ml-1 opacity-60">{n}</span>
		</button>
	{/each}
</div>

<div class="mt-2">
	{#each list as p (p.player_id)}
		{@const t = TONE[p.decision]}
		<div class="border-line border-b last:border-0">
			<PlayerRow {p} wrapSub>
				{#snippet sub()}
					<span class="{t.txt} font-medium">{p.action_summary}</span>
				{/snippet}
			</PlayerRow>
			<div class="-mt-1 flex items-center gap-3 px-1 pb-2.5 text-[11px]">
				<span class="text-muted">media <b class="num text-fg font-medium">{num(p.average_points, 1)}</b></span>
				<span class="text-muted">titular <b class="num text-fg font-medium">{p.start_prob != null ? `${Math.round(p.start_prob * 100)} %` : '–'}</b></span>
				{#if p.in_eleven}<span class="text-accent">en tu once</span>{/if}
				<span class="flex-1"></span>
				{#if p.reasons.length}
					<button class="text-muted flex items-center gap-1" onclick={() => (open = open === p.player_id ? null : p.player_id)}>
						{p.reasons.length} señales
						<svg viewBox="0 0 24 24" class="size-3 transition-transform {open === p.player_id ? 'rotate-90' : ''}" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M9 6l6 6-6 6" /></svg>
					</button>
				{/if}
			</div>
			{#if open === p.player_id}
				<ul class="space-y-1.5 px-1 pb-3 text-xs">
					{#each p.reasons as r, i (i)}
						<li class="flex gap-2">
							<span class="mt-1.5 size-1.5 shrink-0 rounded-full {SEV[r.severity] ?? 'bg-muted'}"></span>
							<span><span class="text-fg font-medium">{r.title}.</span> <span class="text-muted">{r.desc}</span></span>
						</li>
					{/each}
					<li class="flex gap-3 pt-1 text-[11px]">
						<a href="/comparar?p1={p.player_id}" class="text-accent">Comparar</a>
						<a href="/mercado?ver=recomendado&pos={p.position_id}" class="text-accent">Buscar sustituto</a>
					</li>
				</ul>
			{/if}
		</div>
	{:else}
		<p class="text-muted p-5 text-center text-xs">Nadie en este grupo.</p>
	{/each}
</div>

<style>
	.alert {
		background: color-mix(in oklab, var(--color-down) 8%, var(--color-surface));
		border: 1px solid color-mix(in oklab, var(--color-down) 26%, transparent);
	}
</style>
