<script lang="ts">
	// Un rival de un vistazo: qué le falta, cuánto puede gastar, cómo ficha y a quién del mercado
	// podría ir. «Podría» porque no vemos pujas ajenas: son hechos cruzados, no una predicción.
	import { money } from '$lib/format';
	import type { RivalRadar } from '$lib/server/queries';

	let { r, link = true }: { r: RivalRadar; link?: boolean } = $props();
	const pct = (x: number) => `${x >= 0 ? '+' : '−'}${Math.abs(Math.round(x * 100))} %`;
</script>

<div class="border-line border-b px-3 py-2.5 last:border-0">
	<div class="flex items-baseline gap-2">
		{#if link}
			<a href="/liga/{r.team_id}" class="min-w-0 flex-1 truncate font-medium">{r.manager_name}</a>
		{:else}
			<span class="min-w-0 flex-1 truncate font-medium">{r.manager_name}</span>
		{/if}
		<span class="num text-warn shrink-0 text-sm">{r.cash != null ? `≈${money(r.cash)}` : '–'}</span>
	</div>
	<div class="mt-0.5 text-xs {r.can_field ? 'text-muted' : 'text-down font-medium'}">{r.needs_text}</div>
	<div class="text-muted mt-0.5 text-xs">
		{r.signings_30d
			? `${r.signings_30d} ${r.signings_30d === 1 ? 'fichaje' : 'fichajes'} en 30 días`
			: 'Sin fichajes en 30 días'}{#if r.clauses_30d}{' · '}{r.clauses_30d} {r.clauses_30d === 1 ? 'clausulazo' : 'clausulazos'}{/if}{#if r.overpay_median != null}{' · '}paga de mediana <span class="num {r.overpay_median > 0 ? 'text-warn' : ''}">{pct(r.overpay_median)}</span> sobre el valor ({r.overpay_cases} casos){/if}
	</div>
	{#if r.could_bid.length}
		<div class="mt-1 text-xs">
			<span class="text-warn">Podría disputarte:</span>
			{#each r.could_bid.slice(0, 4) as b, i (b.player_id)}{i ? ', ' : ' '}<a href="/jugador/{b.player_id}" class="font-medium">{b.name}</a> <span class="num text-muted">{money(b.price)}</span>{/each}{#if r.could_bid.length > 4}<span class="text-muted"> y {r.could_bid.length - 4} más</span>{/if}
		</div>
	{/if}
</div>
