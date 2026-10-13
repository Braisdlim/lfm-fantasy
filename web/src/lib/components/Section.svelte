<script lang="ts">
	import type { Snippet } from 'svelte';
	// `bare` quita la tarjeta: el diseño separa con filetes y no con cajas, y una caja dentro de
	// otra caja compite con el contenido en una pantalla de 375 px.
	let {
		id,
		title,
		aside,
		children,
		flush = false,
		bare = false
	}: { id?: string; title: string; aside?: Snippet; children: Snippet; flush?: boolean; bare?: boolean } = $props();
</script>

<section {id} class="mt-5 scroll-mt-4">
	<div class="mb-2 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 px-1">
		<h2 class="text-muted text-xs font-semibold tracking-wide uppercase">{title}</h2>
		{#if aside}<div class="text-muted text-xs">{@render aside()}</div>{/if}
	</div>
	<div class={bare ? '' : `card overflow-hidden ${flush ? '' : 'p-3'}`}>{@render children()}</div>
</section>
