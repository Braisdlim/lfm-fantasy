<script lang="ts">
	import type { Snippet } from 'svelte';
	import Delta from './Delta.svelte';
	import PlayerAvatar from './PlayerAvatar.svelte';
	import Sparkline from './Sparkline.svelte';
	import StatusDot from './StatusDot.svelte';
	import { money, num, playerName, POS, POS_BADGE, shortClub } from '$lib/format';
	import type { PlayerCard } from '$lib/server/queries';

	let {
		p,
		sub,
		right,
		compareTo = 'value_1d',
		wrapSub = false,
		showAvatar = true,
		showSparkline = true
	}: {
		p: PlayerCard;
		sub?: Snippet;
		right?: Snippet;
		compareTo?: 'value_1d' | 'value_7d' | 'value_30d';
		wrapSub?: boolean;
		showAvatar?: boolean;
		showSparkline?: boolean;
	} = $props();

	const name = $derived(playerName(p));
</script>

<!-- Fila del tablero: compacta, adaptada a móvil con avatar + escudo del club -->
<a
	href="/jugador/{p.player_id}"
	class="border-line active:bg-surface-2 flex items-center gap-2.5 sm:gap-3 border-b px-1 py-2.5 last:border-0"
>
	<!-- Avatar del jugador con escudo del club superpuesto -->
	{#if showAvatar}
		<PlayerAvatar image={p.image_url} badge={p.badge_url} {name} size="sm" />
	{/if}

	<div class="min-w-0 flex-1">
		<div class="flex items-center gap-1.5 min-w-0">
			<StatusDot status={p.status} class="shrink-0" />
			<span class="truncate text-sm font-bold text-fg">{name}</span>
			<span class="rounded px-1.5 py-0.2 text-[9px] font-black uppercase shrink-0 {POS_BADGE[p.position_id]}">
				{POS[p.position_id]}
			</span>
			<span class="text-muted shrink-0 text-[11px] hidden sm:inline">· {shortClub(p.club)}</span>
		</div>
		<!-- El sub tiene que ser contenido EN LÍNEA. Si wrapSub es true, permite envolver insignias;
		     si es false, trunca para mantener altura fija en listas densas. -->
		<div class="text-muted mt-0.5 {wrapSub ? '' : 'truncate'} text-[11px]">
			{#if sub}{@render sub()}{:else}{p.points_total} pts · media {num(p.average_points, 1)}{/if}
		</div>
	</div>

	{#if showSparkline}
		<div class="hidden sm:block shrink-0">
			<Sparkline values={p.spark} width={38} height={18} />
		</div>
	{/if}

	<div class="flex {right ? 'min-w-[5.25rem] w-auto' : 'w-[5.25rem]'} shrink-0 flex-col items-end text-right">
		{#if right}{@render right()}{:else}
			<span class="num text-[15px] font-bold text-fg">{money(p.value)}</span>
			<Delta now={p.value} before={p[compareTo]} showPct={false} size="text-[11px]" />
		{/if}
	</div>
</a>
