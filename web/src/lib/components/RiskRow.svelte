<script lang="ts">
	// Fila de cláusula tal como la define el diseño de Hoy: sin foto, con un punto de color que dice
	// si está abierta, y **dos líneas fijas**. La segunda va con `truncate`, así que por muchos
	// rivales que haya la fila nunca crece: antes cuatro nombres en rojo la estiraban a cinco
	// renglones y tapaban la cláusula, que es el dato que decide.
	import Sparkline from '$lib/components/Sparkline.svelte';
	import { POS, clauseVsValueShort, money, shortClub } from '$lib/format';

	let {
		p,
		state,
		threats
	}: {
		p: {
			player_id: string;
			name: string;
			nickname: string | null;
			position_id: number;
			club: string;
			value: number;
			buyout_clause: number;
			gap: number;
			spark: number[];
		};
		state: { cls: string; label: string; open: boolean };
		threats: { manager_name: string }[];
	} = $props();

	const g = $derived(clauseVsValueShort(p.gap, p.value));

	/** «N. Boiro y 3 más»: el primero abreviado y el resto contados, que es lo que cabe en la línea.
	 *  Cortar por caracteres dejaba cosas como «Nigrinho Bo…»; con la inicial se lee entero. */
	const quien = $derived.by(() => {
		if (!threats.length) return '';
		const [primero, ...resto] = threats.map((x) => x.manager_name);
		const partes = primero.split(/\s+/);
		const corto = partes.length > 1 ? `${partes[0][0]}. ${partes[partes.length - 1]}` : primero;
		return resto.length ? `${corto} y ${resto.length} más` : corto;
	});
</script>

<a
	href="/jugador/{p.player_id}"
	class="border-line active:bg-surface-2 flex items-center gap-3 border-t px-1 py-2.5"
>
	<div class="min-w-0 flex-1">
		<div class="flex items-center gap-1.5">
			<span class="size-[5px] shrink-0 rounded-full {state.open ? 'bg-down' : 'bg-warn'}"></span>
			<span class="truncate text-sm font-medium">{p.nickname ?? p.name}</span>
			<span class="text-muted shrink-0 text-[11px]">{POS[p.position_id]}</span>
		</div>
		<div class="text-muted mt-0.5 truncate text-[11px]">
			{shortClub(p.club)}{' · '}<span class={state.cls} title={threats.map((x) => x.manager_name).join(', ')}
				>{quien}</span
			>
		</div>
	</div>
	<Sparkline values={p.spark} width={40} height={18} />
	<div class="w-[5.25rem] shrink-0 text-right">
		<div class="num text-[15px] font-medium">{money(p.buyout_clause)}</div>
		<!-- La mono es para cifras, no para frases: «a su valor» en monoespaciada se lee peor. -->
		<div class="mt-0.5 text-[11px] {g.cls}">{g.text}</div>
	</div>
</a>
