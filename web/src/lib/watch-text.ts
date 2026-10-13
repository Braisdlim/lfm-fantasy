import { relative } from './format';

/** Texto de una ocasión de la lista de seguimiento con su plazo al día (no el de la última pasada). */
export function hitText(h: { text: string; closes?: string | null }, now = Date.now()): string {
	const vivo = h.closes && new Date(h.closes).getTime() > now;
	return vivo ? `${h.text} · cierra ${relative(h.closes, now)}` : h.text;
}
