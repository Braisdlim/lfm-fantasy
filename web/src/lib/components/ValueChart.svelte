<script lang="ts">
	import { money } from '$lib/format';

	let {
		series,
		marks = [],
		height = 220
	}: { series: { day: string; value: number; source: string }[]; marks?: { day: string; label: string }[]; height?: number } = $props();

	let el = $state<HTMLDivElement>();
	let failed = $state(false);

	$effect(() => {
		const values = series;
		const annotations = marks;
		const target = el;
		if (!target) return;
		failed = false;
		let chart: { dispose: () => void; resize: () => void } | undefined;
		let ro: ResizeObserver | undefined;
		let cancelled = false;
		(async () => {
			const core = await import('$lib/value-chart');
			if (cancelled) return;
			const c = core.init(target);
			chart = c;
			const first = values[0]?.value ?? 0;
			const last = values[values.length - 1]?.value ?? 0;
			const color = last >= first ? '#22c55e' : '#f43f5e';
			const fmtDay = (v: string) => new Date(v + 'T12:00:00').toLocaleDateString('es-ES', { day: 'numeric', month: 'short' });
			c.setOption({
				animation: false,
				grid: { left: 8, right: 8, top: 12, bottom: 44, containLabel: true },
				tooltip: {
					trigger: 'axis',
					backgroundColor: '#1a222c',
					borderColor: '#243040',
					textStyle: { color: '#e6edf3' },
					formatter: (ps: { axisValue: string; data: number }[]) => `${fmtDay(ps[0].axisValue)}<br/><b>${money(ps[0].data, 2)}</b>`
				},
				xAxis: {
					type: 'category',
					data: values.map((s) => s.day),
					boundaryGap: false,
					axisLine: { lineStyle: { color: '#243040' } },
					axisLabel: { color: '#8b98a8', formatter: fmtDay }
				},
				yAxis: {
					type: 'value',
					scale: true,
					splitLine: { lineStyle: { color: '#1a222c' } },
					axisLabel: { color: '#8b98a8', formatter: (v: number) => money(v, 0) }
				},
				dataZoom: [
					{ type: 'inside' },
					{ type: 'slider', height: 18, bottom: 6, borderColor: '#243040', backgroundColor: '#121820', fillerColor: 'rgba(56,189,248,0.15)', textStyle: { color: '#8b98a8' } }
				],
				series: [
					{
						type: 'line',
						data: values.map((s) => s.value),
						showSymbol: false,
						smooth: 0.2,
						lineStyle: { color, width: 2 },
						areaStyle: {
							color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: color + '55' }, { offset: 1, color: color + '00' }] }
						},
						markLine: annotations.length
							? {
									symbol: 'none',
									label: { color: '#e6edf3', formatter: (m: { name: string }) => m.name, position: 'insideEndTop' },
									lineStyle: { color: '#38bdf8', type: 'dashed' },
									data: annotations.map((m) => ({ xAxis: m.day, name: m.label }))
								}
							: undefined
					}
				]
			});
			ro = new ResizeObserver(() => c.resize());
			ro.observe(target);
		})().catch(() => { if (!cancelled) failed = true; });
		return () => {
			cancelled = true;
			ro?.disconnect();
			chart?.dispose();
		};
	});
</script>

<div bind:this={el} style="height: {height}px" class="w-full" role="img" aria-label="Evolución del valor de mercado: {series.length} días, de {money(series[0]?.value)} a {money(series[series.length - 1]?.value)}"></div>
{#if failed}<p class="text-muted text-xs" role="status">No se pudo cargar el gráfico. Puedes consultar el histórico de valores debajo.</p>{/if}
