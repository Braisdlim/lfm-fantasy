<script lang="ts">
	let { values = [], width = 72, height = 24 }: { values: number[]; width?: number; height?: number } = $props();

	const path = $derived.by(() => {
		const v = values.filter((x) => x != null);
		if (v.length < 2) return '';
		const min = Math.min(...v);
		const max = Math.max(...v);
		const span = max - min || 1;
		return v
			.map((y, i) => `${((i / (v.length - 1)) * (width - 2) + 1).toFixed(1)},${(height - 2 - ((y - min) / span) * (height - 4) + 1).toFixed(1)}`)
			.join(' ');
	});
	const up = $derived(values.length > 1 && values[values.length - 1] >= values[0]);
</script>

{#if path}
	<svg {width} {height} viewBox="0 0 {width} {height}" class="shrink-0" aria-hidden="true">
		<polyline points={path} fill="none" stroke={up ? 'var(--color-up)' : 'var(--color-down)'} stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round" />
	</svg>
{/if}
