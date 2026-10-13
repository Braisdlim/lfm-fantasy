<script lang="ts">
	// «Seguir» a un jugador: lo máximo que pagarías y la titularidad mínima. El job avisa por
	// Telegram cuando está en el mercado o con la cláusula abierta dentro de esas condiciones.
	import { enhance } from '$app/forms';
	import { money, relative } from '$lib/format';
	import type { WatchRule } from '$lib/server/queries';
	import { hitText } from '$lib/watch-text';

	let {
		rule,
		value,
		action = '?/seguir',
		error = null
	}: { rule: WatchRule | null; value: number | null; action?: string; error?: string | null } = $props();

	let editing = $state(false);
	let opened = $state(false);
	const toM = (n: number | null | undefined) => (n == null ? '' : (n / 1e6).toFixed(1).replace('.', ','));
	// Por defecto, un 10 % por encima del valor: margen para pujar sin pasarse.
	const defaultMax = $derived(rule?.max_price != null ? toM(rule.max_price) : value ? toM(Math.ceil((value * 1.1) / 1e5) * 1e5) : '');
	const STATE: Record<string, { label: string; cls: string }> = {
		cumple: { label: 'Se puede fichar', cls: 'text-up' },
		espera: { label: 'En espera', cls: 'text-muted' },
		bloqueado: { label: 'Bloqueado', cls: 'text-down' },
		tuyo: { label: 'Ya es tuyo', cls: 'text-accent' }
	};
	const PCTS = [0, 50, 60, 70, 80];
</script>

<div class="border-line mt-2 rounded-xl border px-3 py-2.5 text-xs">
	{#if rule && !editing}
		{@const st = rule.state ? STATE[rule.state] : null}
		<div class="flex items-start justify-between gap-2">
			<div class="min-w-0">
				<div class="text-fg font-semibold">
					En seguimiento{#if st}{' · '}<span class={st.cls}>{st.label}</span>{/if}
				</div>
				<div class="text-muted mt-0.5">
					{rule.max_price != null ? `hasta ${money(rule.max_price)}` : 'sin límite de precio'}
					{#if rule.min_start_prob != null}{' · '}titular ≥ {Math.round(rule.min_start_prob * 100)} %{/if}
					{' · '}{[rule.watch_market && 'mercado', rule.watch_clause && 'cláusula'].filter(Boolean).join(' y ')}
					{#if rule.note}{' · '}«{rule.note}»{/if}
				</div>
				{#if rule.detail?.hits?.length}
					{#each rule.detail.hits as h (h.kind)}<div class="text-up mt-1">{hitText(h)}</div>{/each}
				{/if}
				{#if rule.detail?.reasons?.length}
					{#each rule.detail.reasons as r (r)}<div class="text-muted mt-1">{r}</div>{/each}
				{/if}
				<div class="text-muted mt-1 text-[11px]">
					{rule.checked_at ? `Comprobado ${relative(rule.checked_at)}` : 'Se comprobará en la próxima pasada (cada 30 min)'}
				</div>
			</div>
			<div class="flex shrink-0 flex-col items-end gap-1.5">
				<button type="button" class="text-accent" onclick={() => (editing = true)}>Editar</button>
				<form method="POST" {action} use:enhance>
					<input type="hidden" name="off" value="1" />
					<button class="text-muted">Dejar de seguir</button>
				</form>
			</div>
		</div>
	{:else if !rule && !opened}
		<button type="button" class="flex min-h-8 w-full items-center justify-between text-left" onclick={() => (opened = true)}>
			<span><span class="text-fg font-semibold">Seguir</span><span class="text-muted"> · te aviso cuando esté a tu precio</span></span>
			<span class="text-accent">＋</span>
		</button>
	{:else}
		<form method="POST" {action} use:enhance={() => async ({ update }) => { await update({ reset: false }); editing = false; }}>
			<div class="text-fg font-semibold">Avísame si se puede fichar</div>
			<div class="mt-2 grid grid-cols-2 gap-2">
				<label class="flex flex-col gap-1">
					<span class="text-muted">Pagaría hasta (M)</span>
					<input name="max_price" inputmode="decimal" value={defaultMax} placeholder="sin límite" class="bg-surface-2 text-fg num min-h-10 rounded-lg px-2.5 outline-none" />
				</label>
				<label class="flex flex-col gap-1">
					<span class="text-muted">Titular mínimo</span>
					<select name="min_start" class="bg-surface-2 text-fg min-h-10 rounded-lg px-2 outline-none">
						{#each PCTS as p (p)}
							<option value={p} selected={Math.round((rule?.min_start_prob ?? 0) * 100) === p}>{p ? `${p} %` : 'Da igual'}</option>
						{/each}
					</select>
				</label>
			</div>
			<div class="mt-2 flex flex-wrap gap-x-4 gap-y-1">
				<label class="flex min-h-8 items-center gap-1.5"><input type="checkbox" name="watch_market" checked={rule?.watch_market ?? true} /> En el mercado</label>
				<label class="flex min-h-8 items-center gap-1.5"><input type="checkbox" name="watch_clause" checked={rule?.watch_clause ?? true} /> Cláusula abierta</label>
			</div>
			<div class="mt-2 flex items-center gap-2">
				<input name="note" maxlength="120" value={rule?.note ?? ''} placeholder="Nota (opcional)" class="bg-surface-2 text-fg placeholder:text-muted min-h-10 min-w-0 flex-1 rounded-lg px-2.5 outline-none" />
				<button class="bg-accent min-h-10 shrink-0 rounded-lg px-3 font-semibold text-black">{rule ? 'Guardar' : 'Seguir'}</button>
			</div>
			<button type="button" class="text-muted mt-1.5" onclick={() => { editing = false; opened = false; }}>Cancelar</button>
			<p class="text-muted mt-1.5">Aviso por Telegram una vez por ocasión. Nunca puja ni clausula por ti.</p>
		</form>
	{/if}
	{#if error}<p class="text-down mt-1.5">{error}</p>{/if}
</div>
