<script lang="ts">
	import PageHeader from '$lib/components/PageHeader.svelte';
	import RivalCard from '$lib/components/RivalCard.svelte';
	import SquadList from '$lib/components/SquadList.svelte';
	import { clauseState, money } from '$lib/format';
	let { data } = $props();
	const t = $derived(data.team as { manager_name: string; position: number; points: number; team_value: number; is_me: boolean });
	const open = $derived(data.players.filter((p) => clauseState(p.clause_locked_until, p.is_shielded).open).length);
	const total = $derived(data.players.reduce((a, p) => a + p.value, 0));
	const clausesTotal = $derived(data.players.reduce((a, p) => a + (p.buyout_clause ?? 0), 0));
</script>

<svelte:head><title>lfm · {t.manager_name}</title></svelte:head>

<PageHeader title={t.manager_name} back="/liga">{t.position}º · {t.points} pts</PageHeader>

<div class="card mt-3 grid grid-cols-3 gap-3 p-4">
	<div><div class="text-muted text-xs">Valor plantilla</div><div class="num text-lg font-semibold">{money(total)}</div></div>
	<div><div class="text-muted text-xs">Suma de cláusulas</div><div class="num text-lg font-semibold">{money(clausesTotal)}</div></div>
	<div><div class="text-muted text-xs">Cláusulas abiertas</div><div class="num text-lg font-semibold {open ? 'text-down' : ''}">{open} / {data.players.length}</div></div>
</div>

{#if data.radar}
	<div class="card mt-3 overflow-hidden"><RivalCard r={data.radar} link={false} /></div>
{/if}

<div class="mt-4">
	<SquadList players={data.players} showBuy={t.is_me} />
</div>
