<script lang="ts">
	import { POS, POS_LONG, fixed, money, playerName, shortClub } from '$lib/format';
	import type { ElevenPlayer, ElevenView } from '$lib/server/queries';

	let { once }: { once: NonNullable<ElevenView> } = $props();

	const starters = $derived(once.starters);
	const goalkeepers = $derived(starters.filter((p) => p.position_id === 1));
	const defenders = $derived(starters.filter((p) => p.position_id === 2));
	const midfielders = $derived(starters.filter((p) => p.position_id === 3));
	const forwards = $derived(starters.filter((p) => p.position_id === 4));

	const POS_RING: Record<number, string> = {
		1: 'border-emerald-400 ring-emerald-500/30',
		2: 'border-blue-400 ring-blue-500/30',
		3: 'border-amber-400 ring-amber-500/30',
		4: 'border-rose-400 ring-rose-500/30'
	};

	function probBadge(p: ElevenPlayer) {
		if (p.injured) return { text: 'Lesionado', cls: 'bg-down text-white' };
		if (p.suspended) return { text: 'Sancionado', cls: 'bg-down text-white' };
		if (p.start_prob == null) return null;
		const pct = Math.round(p.start_prob * 100);
		if (pct >= 80) return { text: `${pct}% tit.`, cls: 'bg-up/25 text-up border border-up/40' };
		if (pct >= 50) return { text: `${pct}% tit.`, cls: 'bg-warn/25 text-warn border border-warn/40' };
		return { text: `${pct}% tit.`, cls: 'bg-down/25 text-down border border-down/40' };
	}
</script>

<div class="relative w-full overflow-hidden rounded-2xl border border-[#1e3323] shadow-2xl">
	<!-- Fondo de campo de fútbol realista con gradiente y bandas de corte de césped -->
	<div class="relative flex min-h-[510px] w-full flex-col justify-between py-6 px-2 sm:px-4 bg-[#0e2114]">
		<!-- Textura de bandas de corte del césped -->
		<div
			class="pointer-events-none absolute inset-0 opacity-25"
			style="background: repeating-linear-gradient(to bottom, #16381e 0px, #16381e 50px, #0e2415 50px, #0e2415 100px);"
		></div>

		<!-- Líneas de cal del campo (SVG táctico) -->
		<svg class="pointer-events-none absolute inset-0 h-full w-full stroke-white/20 stroke-[1.5]" fill="none" preserveAspectRatio="none" viewBox="0 0 400 600">
			<!-- Perímetro exterior con margen -->
			<rect x="18" y="18" width="364" height="564" rx="4" />
			<!-- Línea central -->
			<line x1="18" y1="300" x2="382" y2="300" />
			<!-- Círculo central -->
			<circle cx="200" cy="300" r="50" />
			<circle cx="200" cy="300" r="2.5" class="fill-white/30" />

			<!-- Área grande superior (portería rival) -->
			<rect x="110" y="18" width="180" height="78" />
			<!-- Área pequeña superior -->
			<rect x="148" y="18" width="104" height="30" />
			<!-- Arco superior -->
			<path d="M 160 96 A 46 46 0 0 0 240 96" />

			<!-- Área grande inferior (portería propia) -->
			<rect x="110" y="504" width="180" height="78" />
			<!-- Área pequeña inferior -->
			<rect x="148" y="552" width="104" height="30" />
			<!-- Arco inferior -->
			<path d="M 160 504 A 46 46 0 0 1 240 504" />
			<!-- Punto de penalti inferior -->
			<circle cx="200" cy="535" r="2.5" class="fill-white/30" />
		</svg>

		<!-- Línea 4: Delanteros (arriba en el campo) -->
		<div class="relative z-10 flex items-center justify-around gap-1 pt-1">
			{#each forwards as p (p.player_id)}
				{@render playerNode(p)}
			{/each}
		</div>

		<!-- Línea 3: Medios -->
		<div class="relative z-10 flex items-center justify-around gap-1 py-1">
			{#each midfielders as p (p.player_id)}
				{@render playerNode(p)}
			{/each}
		</div>

		<!-- Línea 2: Defensas -->
		<div class="relative z-10 flex items-center justify-around gap-1 py-1">
			{#each defenders as p (p.player_id)}
				{@render playerNode(p)}
			{/each}
		</div>

		<!-- Línea 1: Portero (abajo en su área) -->
		<div class="relative z-10 flex items-center justify-center pb-1">
			{#each goalkeepers as p (p.player_id)}
				{@render playerNode(p)}
			{/each}
		</div>
	</div>
</div>

<!-- Snippet de ficha individual sobre el césped -->
{#snippet playerNode(p: ElevenPlayer)}
	{@const prob = probBadge(p)}
	<a
		href="/jugador/{p.player_id}"
		class="group flex flex-col items-center transition-transform hover:scale-105 active:scale-95 focus:outline-none"
		style="max-width: 82px;"
	>
		<!-- Avatar circular con foto oficial y badge de posición -->
		<div class="relative mb-1">
			<div class="relative h-11 w-11 sm:h-12 sm:w-12 rounded-full border-2 bg-[#09150d] ring-4 shadow-lg overflow-hidden transition-all group-hover:ring-white/40 {POS_RING[p.position_id] ?? 'border-white/40 ring-white/10'}">
				{#if p.image_url}
					<img
						src={p.image_url}
						alt={p.nickname ?? p.name}
						class="h-full w-full object-cover object-top"
						loading="lazy"
					/>
				{:else}
					<div class="flex h-full w-full items-center justify-center font-bold text-xs text-white/70">
						{POS[p.position_id]}
					</div>
				{/if}
			</div>

			<!-- Escudo del club superpuesto en la esquina inferior derecha -->
			{#if p.badge_url}
				<img
					src={p.badge_url}
					alt=""
					class="absolute -bottom-0.5 -right-0.5 h-4 w-4 rounded-full bg-surface p-0.5 border border-line shadow-xs object-contain"
					loading="lazy"
				/>
			{/if}

			<!-- Indicador de cambio si no está puesto actualmente -->
			{#if !p.current}
				<span
					title="Mete a este jugador en tu once"
					class="absolute -top-1 -right-1 flex h-4 w-4 items-center justify-center rounded-full bg-up text-[9px] font-black text-white shadow-xs"
				>
					+
				</span>
			{/if}
		</div>

		<!-- Etiqueta con Nombre / Apodo -->
		<div class="w-full text-center">
			<div class="truncate rounded-md bg-black/85 px-1.5 py-0.5 text-[10px] sm:text-[11px] font-bold text-white shadow-md backdrop-blur-xs border border-white/10 group-hover:border-accent">
				{playerName(p)}
			</div>

			<!-- Métricas: Puntos esperados xPts + Probabilidad titular -->
			<div class="mt-0.5 flex flex-wrap items-center justify-center gap-1">
				<span class="num rounded bg-[#0b1b10]/95 px-1 py-px text-[9px] font-bold text-emerald-300 border border-emerald-500/30">
					{fixed(p.xpts, 1)} pts
				</span>
				{#if prob}
					<span class="rounded px-1 py-px text-[8px] font-semibold {prob.cls}">
						{prob.text}
					</span>
				{/if}
			</div>
		</div>
	</a>
{/snippet}
