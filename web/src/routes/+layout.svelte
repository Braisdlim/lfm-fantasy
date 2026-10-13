<script lang="ts">
	import '../app.css';
	import TabBar from '$lib/components/TabBar.svelte';
	import MarketBanner from '$lib/components/MarketBanner.svelte';
	import { navigating, page } from '$app/state';
	import { onNavigate } from '$app/navigation';

	let { children } = $props();

	onNavigate((navigation) => {
		if (!document.startViewTransition || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
		return new Promise((resolve) => {
			document.startViewTransition(async () => {
				resolve();
				await navigation.complete;
			});
		});
	});
</script>

<svelte:head>
	<title>lfm</title>
</svelte:head>

{#if navigating.to}
	<div role="status" class="fixed top-0 inset-x-0 z-50 h-[2.5px] bg-accent"><span class="sr-only">Cargando página</span></div>
{/if}

{#if page.url.pathname === '/login'}
	{@render children()}
{:else}
	<a href="#main-content" class="skip-link">Saltar al contenido</a>
	<main id="main-content" class="mx-auto max-w-lg md:max-w-2xl px-4 pt-4 pb-6" tabindex="-1">
		{#if page.data.demo}
			<p class="mb-4 rounded-lg border border-line bg-surface-2 px-3 py-2 text-sm text-fg">
				<strong>Demo</strong> · Jugadores y datos deportivos reales al {page.data.latest}.
				Liga, saldos y operaciones de ejemplo. Los cambios no se guardan.
			</p>
		{/if}
		<MarketBanner fresh={page.data.fresh} />
		{@render children()}
	</main>
	<TabBar />
{/if}
