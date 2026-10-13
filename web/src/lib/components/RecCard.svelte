<script lang="ts">
	import { fixed, money, relative, shortClub } from '$lib/format';
	import type { Rec } from '$lib/server/queries';
	import BidGuide from './BidGuide.svelte';
	import PlayerAvatar from './PlayerAvatar.svelte';
	let { rec }: { rec: Rec } = $props();
	let open = $state(false);
	const tone = $derived(
		rec.verdict === 'pujar'
			? 'text-up'
			: rec.verdict === 'vender'
				? 'text-warn'
				: rec.verdict === 'sin_saldo' || rec.verdict === 'aguantar'
					? 'text-muted'
					: 'text-down'
	);
	/** El calendario, en una palabra. La etiqueta larga («más fácil que la mayoría») no cabe en un
	 *  bloque de dato, y el matiz completo sigue estando entre las razones. */
	const calendario = $derived.by(() => {
		const l = rec.fixture_label ?? '';
		if (!l || l.includes('comparación')) return null;
		if (l.includes('los más fáciles')) return { txt: 'Muy fácil', cls: 'text-up' };
		if (l.includes('fácil')) return { txt: 'Fácil', cls: 'text-up' };
		if (l.includes('los más difíciles')) return { txt: 'Muy difícil', cls: 'text-down' };
		if (l.includes('difícil')) return { txt: 'Difícil', cls: 'text-down' };
		return { txt: 'Normal', cls: 'text-muted' };
	});

	const titulo = $derived(
		rec.verdict === 'pujar'
			? 'Compensa pujar'
			: rec.verdict === 'vender'
				? 'Véndelo'
				: rec.verdict === 'aguantar'
					? 'Aguántalo'
					: rec.verdict === 'sin_saldo'
						? 'Necesita saldo'
						: rec.verdict === 'sin_datos'
							? 'Sin datos para decidir'
							: 'No pujes'
	);
	// Lo que aporta a tu once, que es lo único que puntúa: no hay banquillo en el fantasy gratuito.
	const once = $derived.by(() => {
		// Las recomendaciones antiguas no distinguían un once incompleto de un suplente.
		if (!rec.value_day) return null;
		if (rec.incomplete_eleven) return { txt: 'Incompleto', cls: 'text-warn' };
		if (rec.kind === 'buy' && rec.completes_eleven) return { txt: 'Completa', cls: 'text-up' };
		if (rec.kind === 'sell' && rec.breaks_eleven) return { txt: 'Imprescindible', cls: 'text-warn' };
		if (rec.eleven_gain == null) return null;
		if (rec.eleven_gain < 0.05) return { txt: rec.kind === 'buy' ? 'Suplente' : 'No juega', cls: 'text-muted' };
		return { txt: `${rec.kind === 'buy' ? '+' : '−'}${fixed(rec.eleven_gain, 1)}`, cls: rec.kind === 'buy' ? 'text-up' : 'text-warn' };
	});
</script>

<article class="recommendation border-line border-b px-1 py-5 last:border-0" aria-label="Recomendación para {rec.name}">
	<div class="flex items-start justify-between gap-3">
		<div class="flex min-w-0 items-start gap-3">
			<PlayerAvatar image={rec.image_url} name={rec.name} size="md" />
			<div class="min-w-0">
			<div class="flex items-baseline gap-1.5">
				<a href="/jugador/{rec.player_id}" class="truncate text-[15px] font-semibold">{rec.name}</a>
				{#if rec.club_name}<span class="text-muted shrink-0 text-[11px]">{shortClub(rec.club_name)}</span>{/if}
			</div>
			<div class="mt-1 text-[13px] font-medium {tone}">{titulo}</div>
			{#if rec.rebound}
				<div class="bg-warn/12 text-warn mt-1 inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold">Posible rebote · {rec.rebound}</div>
			{/if}
			{#if rec.thesis}
				<div class="bg-accent/12 text-accent mt-1 inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold">Tu apuesta</div>
			{/if}
			{#if rec.completes_eleven}
				<div class="mt-1 inline-flex items-center gap-1 rounded-full bg-up/12 px-2 py-0.5 text-[10px] font-semibold text-up">
					Sin él no puedes alinear
				</div>
			{/if}
			</div>
		</div>
		{#if rec.kind === 'buy' || rec.verdict === 'vender'}
		<div class="shrink-0 text-right">
			<div class="num text-[18px] font-semibold {rec.score >= 0 ? 'text-up' : 'text-down'}">
				{rec.score >= 0 ? '+' : '−'}{money(Math.abs(rec.score))}
			</div>
			<div class="text-muted mt-px text-[11px]">{rec.kind === 'buy' ? 'margen estimado' : 'balance de vender'}</div>
		</div>
		{/if}
	</div>

	<!-- Tres bloques de dato en vez de texto corrido: la cifra arriba y su palabra debajo, que es
	     como se leen de un vistazo y como los dibujaba el tablero. -->
	<div class="mt-3 flex flex-wrap items-center gap-x-4 gap-y-3">
		{#if rec.xpts != null}
			<div>
				<div class="num text-[13px] font-medium">{rec.xpts === 0 ? '–' : fixed(rec.xpts, 1)}</div>
				<div class="text-muted text-xs">puntos estimados</div>
			</div>
		{/if}
		<div>
			{#if rec.start_prob != null}
				<div
					class="num text-[13px] font-medium {rec.start_prob >= 0.7
						? 'text-up'
						: rec.start_prob <= 0.4
							? 'text-down'
							: 'text-warn'}"
				>
					{Math.round(rec.start_prob * 100)} %
				</div>
				<div class="text-muted text-[10px]">titular estimado</div>
			{:else}
				<div class="text-muted text-[13px]">Sin dato vigente</div>
				<div class="text-muted text-[10px]">titularidad</div>
			{/if}
		</div>
		{#if once}
			<div>
				<div class="num text-[13px] font-medium {once.cls}">{once.txt}</div>
				<div class="text-muted text-[10px]">tu once</div>
			</div>
		{/if}
		<div class="flex-1"></div>
		<button class="text-muted flex min-h-10 shrink-0 items-center gap-1 text-xs" aria-expanded={open} aria-controls="reasons-{rec.id}" onclick={() => (open = !open)}>
			{rec.reasons.length} razones
			<svg viewBox="0 0 24 24" class="size-3 transition-transform {open ? 'rotate-90' : ''}" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M9 6l6 6-6 6" /></svg>
		</button>
	</div>
	<BidGuide {rec} />
	{#if rec.availability_at}
		<p class="text-muted mt-2 text-xs">Titularidad: {#if rec.availability_url}<a class="text-accent underline" href={rec.availability_url} target="_blank" rel="noreferrer">FútbolFantasy</a>{:else}FútbolFantasy{/if} · consultada {relative(rec.availability_at)}.</p>
	{/if}

	{#if rec.club_share != null && rec.club_share >= 0.25}
		<div class="text-warn mt-1 text-xs">
			⚠ Concentración: el {Math.round(rec.club_share * 100)} % de tu plantilla ya es del {rec.club_name}
		</div>
	{/if}
	{#if open}
		<ul id="reasons-{rec.id}" class="text-muted mt-3 space-y-2 text-xs leading-relaxed">
			{#if calendario}<li>Calendario: <span class={calendario.cls}>{calendario.txt}</span>.</li>{/if}
			{#each rec.reasons as r (r.code)}
				<li class="flex gap-2">
					<span class="text-line shrink-0">•</span>
					<span>{r.text}<span class="opacity-50"> ({r.source})</span></span>
				</li>
			{/each}
			<li class="opacity-60">Calculado {relative(rec.created_at)}</li>
		</ul>
	{/if}
</article>
