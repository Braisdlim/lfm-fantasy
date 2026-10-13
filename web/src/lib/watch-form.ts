// Lee el formulario de «Seguir» sin confiar en el navegador: importes en millones con coma o punto,
// titularidad en %, y límites razonables. Devuelve el error en castellano si algo no cuadra.

export type WatchInput = {
	max_price: number | null;
	min_start_prob: number | null;
	watch_market: boolean;
	watch_clause: boolean;
	note: string | null;
};

export function parseMillions(raw: FormDataEntryValue | null): number | null | 'invalid' {
	const s = String(raw ?? '')
		.trim()
		.replace(/\s|M$/gi, '')
		.replace(',', '.');
	if (!s) return null;
	const n = Number(s);
	if (!Number.isFinite(n) || n <= 0 || n > 500) return 'invalid';
	return Math.round(n * 1e6);
}

export function parseWatchForm(form: FormData): { ok: true; rule: WatchInput } | { ok: false; error: string } {
	const max = parseMillions(form.get('max_price'));
	if (max === 'invalid') return { ok: false, error: 'El precio máximo va en millones, por ejemplo 5,5.' };
	const pct = Number(form.get('min_start') ?? 0);
	if (!Number.isFinite(pct) || pct < 0 || pct > 99) return { ok: false, error: 'La titularidad mínima va de 0 a 99 %.' };
	const watch_market = form.get('watch_market') === 'on';
	const watch_clause = form.get('watch_clause') === 'on';
	if (!watch_market && !watch_clause) return { ok: false, error: 'Marca al menos mercado o cláusula.' };
	const note = String(form.get('note') ?? '').trim().slice(0, 120) || null;
	return {
		ok: true,
		rule: { max_price: max, min_start_prob: pct > 0 ? pct / 100 : null, watch_market, watch_clause, note }
	};
}
