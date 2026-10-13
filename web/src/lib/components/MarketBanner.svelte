<script lang="ts">
	import { relative, timeText } from '$lib/format';
	import type { Freshness } from '$lib/server/queries';

	// Aviso único y global de que el mercado de LaLiga está a medio rotar.
	//
	// Antes una captura a medias se guardaba como «el mercado actual» y la app entera cambiaba de
	// golpe: mercado con tres jugadores, cero pujas recomendadas, cuentas atrás a cero. Ahora esas
	// capturas no se guardan y la app sigue enseñando el último ciclo bueno; este aviso es lo único
	// que cambia, para que se sepa por qué los datos son de antes del cierre.
	let { fresh }: { fresh?: Freshness | null } = $props();

	const closed = $derived(!!fresh?.cycle_end && new Date(fresh.cycle_end).getTime() < Date.now());
	const rotating = $derived(closed || fresh?.market_state === 'rotating' || fresh?.market_state === 'empty');
</script>

{#if fresh && rotating}
	<div class="banner mt-2 mb-1 flex items-start gap-2.5 rounded-xl px-3 py-2.5 text-xs leading-snug" role="status">
		<span class="pulse mt-1 h-2 w-2 shrink-0 rounded-full bg-warn"></span>
		<div>
			<div class="text-fg font-medium">LaLiga está rotando el mercado</div>
			<div class="text-muted mt-0.5">
				{#if closed}El ciclo cerró {timeText(fresh.cycle_end)}.{/if}
				Enseñamos el último mercado bueno y sus recomendaciones; se actualiza solo en cuanto LaLiga publique el nuevo{#if fresh.market_state_at}{' '}(último intento {relative(fresh.market_state_at)}){/if}.
			</div>
		</div>
	</div>
{/if}

<style>
	.banner {
		background: color-mix(in oklab, var(--color-warn) 9%, var(--color-surface));
		border: 1px solid color-mix(in oklab, var(--color-warn) 28%, transparent);
	}
	.pulse {
		box-shadow: 0 0 0 0 color-mix(in oklab, var(--color-warn) 60%, transparent);
		animation: pulse 2s infinite;
	}
	@keyframes pulse {
		70% { box-shadow: 0 0 0 6px transparent; }
		100% { box-shadow: 0 0 0 0 transparent; }
	}
</style>
