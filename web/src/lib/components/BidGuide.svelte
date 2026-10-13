<script lang="ts">
	import { dayText, fixed, money, num, signed } from '$lib/format';
	import type { Rec } from '$lib/server/queries';
	let { rec }: { rec: Rec } = $props();
	let entered = $state<string | null>(null);
	const inputValue = $derived(entered ?? String(rec.bid_to_win ?? rec.value ?? 0));
	const amount = $derived(Number(inputValue));
	const profit = $derived((rec.expected_resale ?? 0) + (rec.sport_value ?? 0) - amount);
	const invalid = $derived(inputValue.trim() === '' || !Number.isFinite(amount) || amount < 0);
	const overLimit = $derived(rec.max_bid != null && amount > rec.max_bid);
	const belowMinimum = $derived(amount < (rec.min_price ?? rec.value ?? 0));
	const overCash = $derived(rec.affordable_max != null && amount > rec.affordable_max);
	const cashLimits = $derived(rec.affordable_max != null && rec.max_bid != null && rec.affordable_max < rec.max_bid);
	const days = (n: number) => n >= 7 ? '7+' : num(n, 1);
</script>

<div class="bid-guide">
	{#if rec.kind === 'buy' && rec.max_bid != null}
		<dl class="bid-limits">
			<div><dt>Puja orientativa</dt><dd class="num">{money(rec.bid_to_win, 2)}</dd></div>
			<div><dt>{cashLimits ? 'Límite con tu saldo' : 'Máximo rentable estimado'}</dt><dd class="num text-accent">{money(cashLimits ? rec.affordable_max : rec.max_bid, 2)}</dd></div>
		</dl>
		<p class="text-muted mt-2 text-xs">{cashLimits ? 'Tu saldo limita la puja.' : rec.affordable_max != null ? 'Este máximo ya tiene en cuenta tu saldo.' : 'Límite basado en la rentabilidad estimada.'} No garantiza ganar ni obtener beneficio.</p>
	{/if}

	{#if rec.trend}
		<div class="trend-note">
			{#if rec.trend.status === 'validated' && rec.trend.days != null}
				<p class="font-medium text-fg">Subida estimada: {days(rec.trend.days)} días más</p>
				<p>Es una estimación; puede frenarse antes.</p>
			{:else if rec.trend.status === 'unvalidated'}
				<p>No hay una estimación fiable de cuántos días seguirá subiendo: el modelo no supera su prueba reciente.</p>
			{:else if rec.trend.status === 'insufficient'}
				<p>Está subiendo, pero falta histórico comparable para estimar cuánto durará.</p>
			{:else}
				<p>{rec.trend.streak < 0 ? `Lleva ${rec.trend.streak_censored ? 'al menos ' : ''}${Math.abs(rec.trend.streak)} días bajando.` : 'Sin una racha de subida activa.'}</p>
			{/if}
		</div>
	{/if}

	<details class="bid-details">
		<summary>{rec.kind === 'buy' ? 'Desglose y calculadora de puja' : 'Ver estimación de valor'}</summary>
		<div class="bid-detail-body">
			{#if rec.trend?.status === 'validated' && rec.trend.days != null}
				<p class="text-muted text-xs leading-relaxed">Rango histórico central: {days(rec.trend.low_days ?? 0)}–{days(rec.trend.high_days ?? 0)} días. En el {num((rec.trend.stop_within_3d ?? 0) * 100, 0)} % de casos se frenó antes de tres días. {num(rec.trend.n, 0)} casos similares; 7+ significa al menos siete.</p>
			{/if}
			{#if rec.kind === 'buy' && rec.expected_resale != null}
				<dl class="calculation">
					<div><dt>Reventa estimada a 7 días</dt><dd class="num">{money(rec.expected_resale, 2)}</dd></div>
					<div><dt>Aportación a tu once</dt><dd class="num">+{money(rec.sport_value ?? 0, 2)}</dd></div>
					<div><dt>Margen exigido</dt><dd class="num">−{money(rec.margin_required ?? (rec.value ?? 0) * 0.03, 2)}</dd></div>
					<div class="calculation-total"><dt>Máximo rentable estimado</dt><dd class="num">{money(rec.max_bid, 2)}</dd></div>
				</dl>
				<p class="text-muted text-xs leading-relaxed">La reventa supone una oferta del sistema del 103 % del valor futuro. Los puntos usan el supuesto de 100.000 € por punto. Ninguno es dinero asegurado.</p>
			{/if}
			{#if rec.drift_low != null && rec.drift_high != null}
				<p class="text-sm">En casos similares, el 60 % central de los cambios a siete días estuvo entre
					<strong class="num">{fixed(rec.drift_low * 100, 1)} %</strong> y
					<strong class="num">{fixed(rec.drift_high * 100, 1)} %</strong>.
					<span class="text-muted">{num(rec.drift_n, 0)} observaciones; no es una garantía.</span></p>
			{/if}
			{#if rec.kind === 'buy' && rec.expected_resale != null && rec.verdict !== 'sin_datos'}
				<div class="bid-simulator">
					<label for="bid-{rec.id}" class="text-sm font-medium">Prueba tu puja en euros</label>
					<div class="mt-2 flex items-center gap-3">
						<input id="bid-{rec.id}" type="number" min="0" step="1" inputmode="numeric"
							value={inputValue} oninput={(e) => entered = e.currentTarget.value}
							aria-describedby="bid-result-{rec.id}" class="num bid-input" />
						<span class="text-muted">€</span>
					</div>
					<div id="bid-result-{rec.id}" class="mt-3 text-sm" aria-live="polite">
						{#if invalid}<p class="text-warn">Introduce un importe válido.</p>
						{:else}
							<p>Resultado estimado: <strong class="num {profit >= 0 ? 'text-up' : 'text-down'}">{signed(profit, 2)}</strong></p>
							{#if belowMinimum}<p class="text-warn mt-1">Por debajo del precio mínimo del anuncio.</p>
							{:else if overLimit}<p class="text-warn mt-1">Superas el límite rentable: el margen ya no compensa.</p>
							{:else if overCash}<p class="text-warn mt-1">Superas el saldo asignado a esta compra.</p>
							{:else}<p class="text-muted mt-1">Dentro del límite estimado. No garantiza ganar la subasta.</p>{/if}
						{/if}
					</div>
					<p class="text-muted mt-3 text-xs">Simulación: no envía ninguna puja.</p>
				</div>
			{/if}
			{#if rec.bid_sample != null}
				<p class="text-muted text-xs leading-relaxed">Puja orientativa basada en {num(rec.bid_sample, 0)} precios ganadores de tu liga, ajustada por tendencia. No conocemos las pujas perdedoras: el percentil 70 no implica un 70 % de probabilidad de ganar.</p>
			{/if}
			{#if rec.value_day}<p class="text-muted text-xs">Precios del {dayText(rec.value_day)} · {rec.history_days} días consecutivos de histórico reciente.</p>{/if}
		</div>
	</details>
</div>

<style>
	.bid-guide { margin-top: 1rem; }
	.bid-limits { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .875rem 1rem; border-block: 1px solid var(--color-line); padding-block: .875rem; }
	dt { color: var(--color-muted); font-size: .75rem; line-height: 1.5; }
	.bid-limits dd { margin-top: .25rem; font-size: 1.0625rem; font-weight: 600; }
	.trend-note { margin-top: .875rem; font-size: .75rem; line-height: 1.65; color: var(--color-muted); }
	.bid-details { margin-top: .75rem; }
	summary { cursor: pointer; color: var(--color-accent); font-size: .8125rem; min-height: 2.75rem; padding-block: .75rem; }
	.bid-detail-body { display: grid; gap: 1rem; padding-block: .75rem; }
	.calculation { display: grid; gap: .625rem; }
	.calculation > div { display: flex; justify-content: space-between; gap: 1rem; align-items: baseline; }
	.calculation dd { font-size: .8125rem; white-space: nowrap; }
	.calculation-total { padding-top: .625rem; border-top: 1px solid var(--color-line); }
	.bid-simulator { padding-block: 1rem; border-block: 1px solid var(--color-line); }
	.bid-input { width: 100%; min-width: 0; background: var(--color-bg); border: 1px solid var(--color-line); border-radius: .5rem; padding: .75rem; font-size: 1rem; }
</style>
