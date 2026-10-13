<script lang="ts">
	import PageHeader from '$lib/components/PageHeader.svelte';
	import PlayerRow from '$lib/components/PlayerRow.svelte';
	import Section from '$lib/components/Section.svelte';
	import { money, relative } from '$lib/format';
	import type { WatchItem } from '$lib/server/queries';
	import { hitText } from '$lib/watch-text';

	let { data } = $props();
	const saldo = $derived(data.team?.team_money ?? null);
	const grupos = $derived([
		{ title: 'Se pueden fichar', items: data.items.filter((i) => i.state === 'cumple') },
		{ title: 'En espera', items: data.items.filter((i) => !i.state || i.state === 'espera') },
		{ title: 'Bloqueados o ya tuyos', items: data.items.filter((i) => i.state === 'bloqueado' || i.state === 'tuyo') }
	]);
	const regla = (i: WatchItem) =>
		[
			i.max_price != null ? `hasta ${money(i.max_price)}` : 'sin límite',
			i.min_start_prob != null ? `titular ≥ ${Math.round(i.min_start_prob * 100)} %` : null
		]
			.filter(Boolean)
			.join(' · ');
	const ultima = $derived(
		data.items.map((i) => i.checked_at).filter(Boolean).sort().at(-1) ?? null
	);
</script>

<svelte:head><title>lfm · Seguimiento</title></svelte:head>

<PageHeader title="Seguimiento" fresh={data.fresh} shows="mercado" back="/" />

<p class="text-muted px-1 pt-1 text-xs">
	Te aviso por Telegram cuando un jugador de esta lista está en el mercado o con la cláusula abierta a tu precio.
	Se añaden, editan y quitan desde la ficha de cada jugador. {#if ultima}Última comprobación {relative(ultima)}.{/if}
</p>

{#if !data.items.length}
	<div class="card text-muted mt-4 p-4 text-sm">
		Aún no sigues a nadie. Busca un jugador, abre su ficha y pulsa «Seguir».
		<a href="/buscar" class="text-accent mt-2 block">Buscar jugador →</a>
	</div>
{/if}

{#each grupos as g (g.title)}
	{#if g.items.length}
		<Section title={g.title} flush bare>
			{#snippet aside()}{g.items.length}{/snippet}
			{#each g.items as i (i.player_id)}
				<PlayerRow p={i} wrapSub>
					{#snippet sub()}
						<span>{regla(i)}</span>
						{#if i.detail?.hits?.length}
							{#each i.detail.hits as h (h.kind)}
								<span class="text-up block">{hitText(h)}{#if saldo != null && h.price > saldo}{' · '}<span class="text-down">te faltan {money(h.price - saldo)}</span>{/if}</span>
							{/each}
						{:else if i.detail?.reasons?.length}
							<span class="block">{i.detail.reasons[0]}</span>
						{:else if !i.checked_at}
							<span class="block">Se comprobará en la próxima pasada</span>
						{/if}
					{/snippet}
				</PlayerRow>
			{/each}
		</Section>
	{/if}
{/each}
