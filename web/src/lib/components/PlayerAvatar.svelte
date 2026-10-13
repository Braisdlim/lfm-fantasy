<script lang="ts">
	let {
		image,
		badge,
		name,
		size = 'sm'
	}: {
		image?: string | null;
		badge?: string | null;
		name: string;
		size?: 'xs' | 'sm' | 'md';
	} = $props();

	let imgFailed = $state(false);
	let badgeFailed = $state(false);

	const initial = $derived((name || '?').trim().charAt(0).toUpperCase());

	const sizeClasses = $derived(
		size === 'xs'
			? { box: 'w-7 h-7 text-[10px]', badge: 'w-3 h-3 -bottom-0.5 -right-0.5' }
			: size === 'md'
				? { box: 'w-11 h-11 text-xs', badge: 'w-4 h-4 -bottom-1 -right-1' }
				: { box: 'w-9 h-9 text-xs', badge: 'w-3.5 h-3.5 -bottom-0.5 -right-0.5' }
	);
</script>

<div class="relative shrink-0 select-none {sizeClasses.box}">
	<!-- Avatar del jugador -->
	<div
		class="h-full w-full rounded-full overflow-hidden border border-line bg-surface-2 flex items-center justify-center shadow-xs"
	>
		{#if image && !imgFailed}
			<img
				src={image}
				alt={name}
				class="h-full w-full object-cover object-top"
				loading="lazy"
				onerror={() => (imgFailed = true)}
			/>
		{:else}
			<span class="font-bold text-muted">{initial}</span>
		{/if}
	</div>

	<!-- Escudo del club superpuesto en la esquina inferior derecha -->
	{#if badge && !badgeFailed}
		<img
			src={badge}
			alt=""
			class="absolute {sizeClasses.badge} rounded-full bg-surface p-0.5 border border-line shadow-xs object-contain"
			loading="lazy"
			onerror={() => (badgeFailed = true)}
		/>
	{/if}
</div>
