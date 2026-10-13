<script lang="ts">
	// ¿Acertaron las recomendaciones? Se juzgan a los siete días, el mismo horizonte con el que se
	// tomaron. Sin esto la app solo se puede creer a sí misma.
	import Section from '$lib/components/Section.svelte';
	import { dayText, money, signed } from '$lib/format';
	import type { Judged, Verdict } from '$lib/server/queries';

	let {
		data
	}: { data: { pending: number; firstVerdictOn: string | null; verdicts: Verdict[]; judged: Judged[] } } =
		$props();

	const ETIQUETA: Record<string, string> = {
		pujar: 'Dijo que pujaras',
		no_pujar: 'Dijo que no pujaras',
		sin_saldo: 'No te llegaba el saldo',
		vender: 'Dijo que vendieras',
		aguantar: 'Dijo que aguantaras',
		sin_datos: 'Sin datos para decidir'
	};

	const total = $derived(data.verdicts.reduce((a, v) => a + v.n, 0));
	const conBeneficio = $derived(data.verdicts.reduce((a, v) => a + v.con_beneficio, 0));
	const aciertos = $derived(data.verdicts.reduce((a, v) => a + v.aciertos, 0));
	const beneficio = $derived(data.verdicts.reduce((a, v) => a + v.beneficio, 0));

	/** Con pocos casos no se saca conclusión: se dice cuántos hay y ya. */
	const FIABLE_DESDE = 10;
</script>

{#if total === 0}
	<Section title="¿Acertó?">
		<p class="text-sm leading-snug">
			Todavía no hay ningún veredicto.
			{#if data.pending}
				Hay <span class="num font-semibold">{data.pending}</span> recomendaciones esperando
				{#if data.firstVerdictOn}
					y la primera se juzga el {dayText(data.firstVerdictOn, { day: 'numeric', month: 'long' })}.
				{:else}
					turno.
				{/if}
			{/if}
		</p>
		<p class="text-muted mt-2 text-xs leading-relaxed">
			Cada recomendación se guarda con las cifras que la sostenían y se juzga <b>siete días
			después</b>, que es el mismo horizonte con el que se tomó: si el consejo era pujar, se mira si
			alguien se lo llevó, si tu puja habría bastado y cuánto habrías ganado o perdido siguiéndolo.
			Hasta que pase ese plazo no hay nada que enseñar, y un número inventado sería peor que ninguno.
		</p>
	</Section>
{:else}
	<Section title="¿Acertó?">
		{#snippet aside()}{total} decisiones juzgadas{/snippet}
		{#if conBeneficio >= FIABLE_DESDE}
			<p class="text-sm leading-snug">
				De las <span class="num font-semibold">{conBeneficio}</span> decisiones con dinero de por medio,
				salieron bien <span class="num font-semibold">{aciertos}</span>. Haberle hecho caso a todo
				habría dejado
				<span class="num font-semibold {beneficio >= 0 ? 'text-up' : 'text-down'}">{signed(beneficio)}</span>.
			</p>
		{:else}
			<p class="text-sm leading-snug">
				Solo hay <span class="num font-semibold">{conBeneficio}</span>
				{conBeneficio === 1 ? 'decisión' : 'decisiones'} con dinero de por medio: son muy pocas para sacar
				un porcentaje que suene a verdad. Abajo están una por una.
			</p>
		{/if}
		<p class="text-muted mt-2 text-xs leading-snug">
			Juzgadas a los siete días, el mismo plazo con el que se decidieron.
		</p>
	</Section>

	{#if conBeneficio >= FIABLE_DESDE}
		<Section title="Por tipo de consejo" flush>
			{#each data.verdicts as v (v.verdict + v.kind)}
				<div class="border-line flex items-baseline gap-2 border-b px-3 py-2.5 last:border-0">
					<div class="min-w-0 flex-1">
						<div class="text-sm font-medium">{ETIQUETA[v.verdict] ?? v.verdict}</div>
						<div class="text-muted text-xs">
							{v.n}
							{v.n === 1 ? 'vez' : 'veces'}{#if v.pujas}, y tu puja habría bastado {v.pujas_ok} de {v.pujas}{/if}
						</div>
					</div>
					{#if v.con_beneficio}
						<div class="shrink-0 text-right">
							<div class="num text-sm font-semibold {v.beneficio >= 0 ? 'text-up' : 'text-down'}">
								{signed(v.beneficio)}
							</div>
							<div class="text-muted text-[11px]">{v.aciertos} de {v.con_beneficio} salieron bien</div>
						</div>
					{/if}
				</div>
			{/each}
		</Section>
	{/if}

	<Section title="Una por una" flush>
		{#snippet aside()}lo último primero{/snippet}
		{#each data.judged as j (j.player_id + j.decided_at + j.kind)}
			<a href="/jugador/{j.player_id}" class="border-line active:bg-surface-2 block border-b px-3 py-2.5 last:border-0">
				<div class="flex items-baseline gap-2">
					<span class="min-w-0 flex-1 truncate text-sm font-medium">{j.name}</span>
					{#if j.profit_if_taken != null}
						<span class="num shrink-0 text-sm font-semibold {j.profit_if_taken >= 0 ? 'text-up' : 'text-down'}">
							{signed(j.profit_if_taken)}
						</span>
					{/if}
				</div>
				<div class="text-muted mt-0.5 text-xs leading-snug">
					{ETIQUETA[j.verdict] ?? j.verdict} el {dayText(j.decided_at)}{#if j.bid}, hasta {money(j.bid)}{/if}
				</div>
				<div class="text-muted text-xs leading-snug">
					{#if j.sold === false}
						No se lo llevó nadie.
					{:else if j.would_have_won === true}
						Se lo llevaron por {money(j.paid)} y tu puja habría bastado.
					{:else if j.would_have_won === false}
						Se lo llevaron por {money(j.paid)}, más de lo que ibas a pujar.
					{:else if j.sold}
						Se lo llevaron por {money(j.paid)}.
					{/if}
					{#if j.real_return != null}
						Su valor cambió {signed(j.real_return)} en la semana{#if j.predicted_return != null}, y se
							esperaba {signed(j.predicted_return)}{/if}.
					{/if}
				</div>
			</a>
		{/each}
	</Section>
{/if}
