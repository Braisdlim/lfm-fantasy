<script lang="ts">
	import { page } from '$app/state';
	import { preloadData } from '$app/navigation';

	const tabs = [
		{ href: '/', label: 'Hoy', icon: 'M3 12l9-8 9 8v8a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z' },
		{ href: '/plantilla', label: 'Plantilla', icon: 'M12 3a4 4 0 1 1 0 8 4 4 0 0 1 0-8zm-7 17a7 7 0 0 1 14 0z' },
		{ href: '/mercado', label: 'Mercado', icon: 'M3 17l6-6 4 4 8-8M14 7h7v7' },
		{ href: '/jornada', label: 'Jornada', icon: 'M4 6a1 1 0 0 1 1-1h14a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1zM4 10h16M9 3v4M15 3v4' },
		{ href: '/liga', label: 'Liga', icon: 'M8 21h8M12 17v4M5 4h14v3a7 7 0 0 1-14 0zM5 6H3v2a3 3 0 0 0 3 3M19 6h2v2a3 3 0 0 1-3 3' }
	];
	const active = (href: string) => (href === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(href));
</script>

<nav class="tabbar border-line fixed inset-x-0 bottom-0 z-20 border-t" style="padding-bottom: env(safe-area-inset-bottom)">
	<div class="mx-auto flex max-w-lg md:max-w-2xl">
		{#each tabs as t (t.href)}
			<a
				href={t.href}
				data-sveltekit-preload-data="hover"
				aria-current={active(t.href) ? 'page' : undefined}
				onpointerdown={() => preloadData(t.href)}
				class="relative flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px] transition-colors {active(t.href) ? 'text-accent font-semibold' : 'text-muted hover:text-fg'}"
			>
				{#if active(t.href)}<span class="bg-accent absolute top-0 h-[2px] w-8 rounded-b-full shadow-[0_0_10px_var(--color-accent)]"></span>{/if}
				<svg viewBox="0 0 24 24" class="h-6 w-6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d={t.icon} /></svg>
				{t.label}
			</a>
		{/each}
	</div>
</nav>

<style>
	.tabbar {
		background: color-mix(in oklab, var(--color-surface) 82%, transparent);
		-webkit-backdrop-filter: saturate(160%) blur(16px);
		backdrop-filter: saturate(160%) blur(16px);
	}
</style>
