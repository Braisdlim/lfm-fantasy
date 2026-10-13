<script lang="ts">
	import type { Snippet } from 'svelte';
	import { dayText, relative } from '$lib/format';
	import type { Freshness } from '$lib/server/queries';

	let {
		title,
		fresh,
		shows = 'valores',
		children,
		back
	}: {
		title: string;
		fresh?: Freshness | null;
		/** qué dato manda en esta pantalla, para decir su antigüedad y no una fecha global */
		shows?: 'valores' | 'mercado' | 'plantilla';
		children?: Snippet;
		back?: string;
	} = $props();

	let open = $state(false);
	const at = $derived(shows === 'mercado' ? fresh?.market : shows === 'plantilla' ? fresh?.squad : null);
	const label = $derived(
		fresh?.values_day && fresh?.values_expected && fresh.values_day < fresh.values_expected
			? `valores del ${dayText(fresh.values_day)}`
			: at
				? relative(at)
				: fresh?.values_day
					? `valores del ${dayText(fresh.values_day)}`
					: ''
	);
	// El mercado se relee cada hora: si el dato pasa de tres horas, algo no está recogiendo y
	// tiene que verse sin abrir el detalle.
	// Los valores de LaLiga cambian a las 00:15: si ya se publicaron los de hoy y aquí siguen los de
	// ayer, cada «hoy» de la app es en realidad el cambio de ayer. Tiene que verse.
	const valuesStale = $derived(!!fresh?.values_day && !!fresh?.values_expected && fresh.values_day < fresh.values_expected);
	const stale = $derived((!!at && Date.now() - new Date(at).getTime() > 3 * 3600_000) || valuesStale);
</script>

<header class="flex flex-wrap items-center justify-between gap-x-2 gap-y-1 pb-1">
	<div class="flex min-w-0 items-center gap-2">
		{#if back}
			<a href={back} class="text-muted -ml-1 p-1" aria-label="Volver">
				<svg viewBox="0 0 24 24" class="h-6 w-6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 18l-6-6 6-6" /></svg>
			</a>
		{/if}
		<h1 class="truncate text-2xl font-bold tracking-tight">{title}</h1>
	</div>
	<div class="text-muted flex shrink-0 items-center gap-2 text-xs">
		{#if children}
			{@render children()}
		{:else if label}
			<button onclick={() => (open = !open)} aria-expanded={open} aria-label="Actualización de datos: {label}" class="flex min-h-11 items-center gap-1.5 {stale ? 'text-warn' : 'text-muted'}">
				<span class="size-1.5 rounded-full {stale ? 'bg-warn' : 'bg-up'}"></span>{label}
			</button>
		{/if}
		{#if !back && title !== 'Buscar'}
			<a href="/buscar" class="text-muted hover:text-fg flex min-h-11 min-w-11 items-center justify-center gap-1.5 rounded-lg px-2" aria-label="Buscar jugador">
				<svg viewBox="0 0 24 24" class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></svg>
				<span class="text-xs font-medium">Buscar</span>
			</a>
		{/if}
	</div>
</header>

{#if fresh?.availability_stale}
	<p class="text-warn mt-3 text-sm" role="status">Las titularidades están desactualizadas{fresh.availability ? ` (${relative(fresh.availability)})` : ''}. Los porcentajes antiguos se ocultan hasta renovar la fuente; revisa las estimaciones de puntos y puja.</p>
{/if}

{#if open && fresh}
	<div class="card text-muted mt-2 p-3 text-xs leading-relaxed">
		<div><b>Mercado y ofertas:</b> {fresh.market ? relative(fresh.market) : '–'}. Se relee cada hora.</div>
		<div><b>Plantillas y cláusulas:</b> {fresh.squad ? relative(fresh.squad) : '–'}.</div>
		<div><b>Titularidades · FútbolFantasy:</b> {fresh.availability ? relative(fresh.availability) : 'sin datos'}. Se revisan cada seis horas; son estimaciones.</div>
		{#if valuesStale}
			<div class="text-warn">
				<b>Valores de ayer.</b> LaLiga ya publicó los del {dayText(fresh.values_expected)} y todavía no se han recogido:
				los cambios «de hoy» que ves son los del {dayText(fresh.values_day)}.
			</div>
		{/if}
		<div>
			<b>Valores de mercado:</b> del {fresh.values_day ? dayText(fresh.values_day) : '–'}. LaLiga los actualiza una
			sola vez al día, a las 00:15, así que releerlos más a menudo no aportaría nada.
		</div>
	</div>
{/if}
