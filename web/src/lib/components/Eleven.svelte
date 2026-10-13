<script lang="ts">
	// El once que conviene poner. Lo calcula `analysis/eleven.py` y aquí solo se cuenta.
	import PitchEleven from '$lib/components/PitchEleven.svelte';
	import PlayerAvatar from '$lib/components/PlayerAvatar.svelte';
	import Section from '$lib/components/Section.svelte';
	import { POS, POS_LONG, POS_PLURAL, fixed, playerName } from '$lib/format';
	import type { ElevenView } from '$lib/server/queries';

	let { once }: { once: NonNullable<ElevenView> } = $props();

	let viewMode = $state<'pitch' | 'list'>('pitch');

	const LINEAS = [
		{ pos: 1, titulo: 'Portería' },
		{ pos: 2, titulo: 'Defensa' },
		{ pos: 3, titulo: 'Medios' },
		{ pos: 4, titulo: 'Delantera' }
	];

	const entran = $derived(once.starters.filter((p) => !p.current));
	const salen = $derived(once.bench.filter((p) => p.current));
	const puestoYa = $derived(entran.length === 0 && salen.length === 0);
	const baja = (p: NonNullable<ElevenView>['bench'][number]) =>
		p.status === 'out_of_league' ? 'fuera de liga' : p.injured || p.status === 'injured'
			? 'lesionado' : p.suspended || p.status === 'suspended' ? 'sancionado' : null;

	/** El titular del que menos puntos se esperan: por ahí es por donde se pierde la jornada. */
	const debil = $derived(
		once.starters.reduce((peor, p) => ((p.xpts ?? 0) < (peor.xpts ?? 0) ? p : peor), once.starters[0])
	);

	const prob = (p: { start_prob: number | null }) =>
		p.start_prob == null ? 'sin dato de titularidad' : `${Math.round(p.start_prob * 100)} % titular`;
	/** La misma cifra dentro de una frase, donde "20 % titular" suelto no se lee. */
	const probFrase = (p: { start_prob: number | null }) =>
		p.start_prob == null
			? 'y no sabemos si será titular'
			: `y sale de titular el ${Math.round(p.start_prob * 100)} % de las veces`;
</script>

<div class="mt-3 mb-3 flex items-center justify-between">
	<div>
		<span class="num text-base font-extrabold text-fg">{fixed(once.xpts, 1)} pts</span>
		<span class="text-xs text-muted">esperados · <strong class="text-fg">{once.formation}</strong></span>
	</div>
	<!-- Switch Campo / Lista -->
	<div class="bg-surface-2 flex rounded-lg p-0.5 text-xs font-semibold">
		<button
			class="rounded-md px-2.5 py-1 transition-all {viewMode === 'pitch' ? 'bg-surface text-fg font-bold shadow-xs' : 'text-muted hover:text-fg'}"
			onclick={() => (viewMode = 'pitch')}
		>
			Campo
		</button>
		<button
			class="rounded-md px-2.5 py-1 transition-all {viewMode === 'list' ? 'bg-surface text-fg font-bold shadow-xs' : 'text-muted hover:text-fg'}"
			onclick={() => (viewMode = 'list')}
		>
			Lista
		</button>
	</div>
</div>

{#if viewMode === 'pitch'}
	<div class="mb-3">
		<PitchEleven {once} />
	</div>
{/if}

<Section title="Tu once">
	{#snippet aside()}{once.formation ?? '–'}{/snippet}
	<p class="text-sm leading-snug">
		<span class="num text-lg font-semibold">{fixed(once.xpts, 1)}</span> puntos esperados en la próxima
		jornada, en {once.formation}.
	</p>
	{#if once.forced}
		<p class="text-muted mt-2 text-xs leading-snug">
			Tienes once jugadores disponibles: el {once.formation} es la única formación que puedes montar
			y juegan los once. Con otro jugador disponible podrás elegir.
		</p>
	{:else}
		<p class="text-muted mt-2 text-xs leading-snug">
			Elegido entre las {once.feasible} formaciones que puedes montar con esta plantilla, de las siete
			que permite el juego.
		</p>
	{/if}

	{#if puestoYa}
		<p class="text-up mt-2 text-xs font-medium">✓ Coincide con tu última alineación capturada.</p>
	{:else}
		<div class="border-warn/40 bg-warn/10 mt-3 rounded-xl border p-2.5">
			<p class="text-warn text-xs font-semibold">Cambios respecto a tu última alineación capturada</p>
			<ul class="mt-1.5 space-y-1 text-xs leading-snug">
				{#each entran as p, i (p.player_id)}
					<li>
						Mete a <a href="/jugador/{p.player_id}" class="text-fg font-medium">{playerName(p)}</a>
						{#if salen[i]}
							en lugar de <a href="/jugador/{salen[i].player_id}" class="text-fg font-medium">{playerName(salen[i])}</a>
						{/if}
						<span class="text-muted">({fixed(p.xpts, 1)} puntos esperados{#if salen[i] && baja(salen[i])}; {playerName(salen[i])}: {baja(salen[i])}{:else if salen[i]} frente a {fixed(salen[i].xpts, 1)}{/if})</span>
					</li>
				{/each}
			</ul>
		</div>
	{/if}
</Section>

{#if viewMode === 'list'}
	<Section title="Quién juega" flush>
		{#snippet aside()}puntos esperados{/snippet}
		{#each LINEAS as linea (linea.pos)}
			{@const gente = once.starters.filter((p) => p.position_id === linea.pos)}
			{#if gente.length}
				<div class="text-muted bg-surface-2/40 px-3 py-1 text-[11px] font-semibold tracking-wide uppercase">
					{linea.titulo}
				</div>
				{#each gente as p (p.player_id)}
					{@const name = playerName(p)}
					<a href="/jugador/{p.player_id}" class="border-line active:bg-surface-2 flex items-center gap-2.5 border-b px-3 py-2 last:border-0">
						<PlayerAvatar image={p.image_url} badge={p.badge_url} {name} size="xs" />
						<span class="min-w-0 flex-1 truncate text-sm font-medium">{name}</span>
						<span class="text-muted shrink-0 text-xs">{prob(p)}</span>
						<span class="num w-10 shrink-0 text-right text-sm font-semibold {(p.xpts ?? 0) < 1 ? 'text-down' : ''}">{fixed(p.xpts, 1)}</span>
					</a>
				{/each}
			{/if}
		{/each}
	</Section>
{/if}

{#if debil}
	<Section title="Por dónde pierdes la jornada">
		<p class="text-sm leading-snug">
			<a href="/jugador/{debil.player_id}" class="font-medium">{playerName(debil)}</a> juega
			de {POS_LONG[debil.position_id]?.toLowerCase() ?? POS[debil.position_id]}, solo se esperan
			<span class="num font-semibold">{fixed(debil.xpts, 1)}</span> puntos de él {probFrase(debil)}.
		</p>
		<p class="text-muted mt-2 text-xs leading-snug">
			{#if once.forced}
				No puedes sentarlo porque no tienes recambio en su puesto: la única forma de arreglarlo es fichar.
			{:else}
				Es el titular del que menos se espera de todo el once.
			{/if}
		</p>
		<a href="/mercado?ver=chollos&pos={debil.position_id}" class="bg-surface-2 mt-3 inline-block rounded-lg px-3 py-1.5 text-xs font-medium">
			Ver {POS_PLURAL[debil.position_id] ?? 'jugadores'} que rinden más de lo que cuestan →
		</a>
	</Section>
{/if}

{#if once.bench.length}
	<Section title="Se quedan fuera" flush>
		{#each once.bench as p (p.player_id)}
			<a href="/jugador/{p.player_id}" class="border-line flex items-baseline gap-2 border-b px-3 py-2 last:border-0">
				<span class="bg-surface-2 text-muted shrink-0 rounded px-1 py-px text-[10px] font-semibold">{POS[p.position_id]}</span>
				<span class="min-w-0 flex-1 truncate text-sm">{p.nickname ?? p.name}</span>
				<span class="text-muted shrink-0 text-xs">{baja(p) ?? prob(p)}</span>
				<span class="num w-10 shrink-0 text-right text-sm">{baja(p) ? '–' : fixed(p.xpts, 1)}</span>
			</a>
		{/each}
	</Section>
{/if}
