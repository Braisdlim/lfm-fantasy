<script lang="ts">
	import { onMount } from 'svelte';
	// `bare` lo saca de su tarjeta: el diseño de Hoy separa los dos plazos con un filete, no con
	// dos cajas. En Mercado se sigue usando con tarjeta.
	let { to, label, bare = false }: { to: string | null; label: string; bare?: boolean } = $props();
	let now = $state(Date.now());
	onMount(() => {
		const id = setInterval(() => (now = Date.now()), 1000);
		return () => clearInterval(id);
	});
	// Un plazo cumplido no es un plazo de cero segundos. Con `Math.max(0, …)` a secas el contador se
	// quedaba clavado en 00:00:00, que se lee como "está a punto" cuando en realidad ya pasó.
	const past = $derived(!!to && new Date(to).getTime() <= now);
	const parts = $derived.by(() => {
		if (!to || past) return null;
		let s = Math.max(0, Math.floor((new Date(to).getTime() - now) / 1000));
		const d = Math.floor(s / 86400);
		s -= d * 86400;
		const h = Math.floor(s / 3600);
		s -= h * 3600;
		const m = Math.floor(s / 60);
		s -= m * 60;
		return { d, h, m, s };
	});
	const urgent = $derived(parts != null && parts.d === 0 && parts.h < 2);
</script>

<div class={bare ? '' : 'card flex-1 p-3'}>
	<div class="text-muted text-[11px] font-medium">{label}</div>
	{#if parts}
		<div class="num mt-0.5 {bare ? 'text-xl' : 'text-xl font-semibold'} {urgent ? 'text-warn' : ''}">
			{#if parts.d > 0}{parts.d} d {parts.h} h{:else}{String(parts.h).padStart(2, '0')}:{String(parts.m).padStart(2, '0')}:{String(parts.s).padStart(2, '0')}{/if}
		</div>
	{:else if past}
		<div class="text-muted mt-1 text-xl">ya pasó</div>
	{:else}
		<div class="text-muted mt-1 text-xl">–</div>
	{/if}
</div>
