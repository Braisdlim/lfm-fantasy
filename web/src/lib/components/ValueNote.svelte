<script lang="ts">
	import { money, moveSentence, moveText, pct, pctText, priceVerdict, SYSTEM_OFFER_BAND } from '$lib/format';
	let {
		price,
		value,
		day,
		spark = [],
		fromLeague = false
	}: { price: number; value: number; day?: string | null; spark?: number[]; fromLeague?: boolean } = $props();
	let open = $state(false);
	const v = $derived(priceVerdict(price, value));
	// La liga abre cada ciclo con el precio igual al valor del día (13 de 13 comprobados el 8-sep)
	const atValue = $derived(v.atValue);
</script>

<button
	class="text-left"
	onclick={(e) => {
		e.preventDefault();
		open = !open;
	}}
>
	{#if atValue}
		<!-- "precio = valor" no aporta nada: lo que importa es hacia dónde se mueve -->
		<span class="num text-xs whitespace-nowrap {(spark.at(-1) ?? 0) >= (spark.at(-2) ?? 0) ? 'text-up' : 'text-down'}">{moveText(spark)}</span>
	{:else}
		<span class="num text-xs {v.cls}">{pctText(pct(price, value))} vs valor</span>
	{/if}
</button>
{#if open}
	<div class="bg-surface-2 text-muted mt-1 rounded-lg p-2 text-left text-xs leading-relaxed">
		<div>
			<b>Valor oficial:</b> {money(value, 2)}. Es el <span class="font-mono">marketValue</span> que publica LaLiga,
			el mismo de la app oficial{#if day}, del {day}{/if}.
		</div>
		{#if atValue}
			<div class="mt-1">{moveSentence(spark)}</div>
			<div class="mt-1">
				<b>Piden exactamente su valor.</b>
				{#if fromLeague}
					La liga abre cada ciclo con el precio igual al valor de ese día, así que aquí el porcentaje no dice nada.
					Lo que decide es hacia dónde va el valor y cuánto pujes: se puja a ciegas y gana la puja más alta.
				{:else}
					Ni caro ni barato respecto al precio oficial. Lo que decide es la tendencia y lo que aceptes negociar.
				{/if}
			</div>
		{:else}
			<div class="mt-1">
				<b>Piden:</b> {money(price, 2)}, un {pctText(pct(price, value))} sobre ese valor. Está {v.text}.
			</div>
		{/if}
		<div class="mt-1">
			Referencia: en 75 ventas al sistema de tu liga pagó entre el {Math.round(SYSTEM_OFFER_BAND.min * 100)} % y el
			{Math.round(SYSTEM_OFFER_BAND.max * 100)} % del valor, con media del {Math.round(SYSTEM_OFFER_BAND.avg * 100)} %.
			Para este jugador, entre {money(value * SYSTEM_OFFER_BAND.min)} y {money(value * SYSTEM_OFFER_BAND.max)}.
		</div>
	</div>
{/if}
