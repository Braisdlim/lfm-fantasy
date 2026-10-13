import { error, fail } from '@sveltejs/kit';
import { myTeam, player, setThesis, setWatch, thesis, watchRule } from '$lib/server/queries';
import { parseWatchForm } from '$lib/watch-form';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params }) => {
	const [me, p, t, w] = await Promise.all([myTeam(), player(params.id), thesis(params.id), watchRule(params.id)]);
	if (!p) error(404, 'Jugador no encontrado');
	return { me, ...p, thesis: t, watch: w };
};

export const actions: Actions = {
	// Marcar o quitar «es mi apuesta». Solo escribe en nuestra base, nunca en LaLiga.
	apuesta: async ({ params, request }) => {
		const form = await request.formData();
		const on = form.get('on') === '1';
		const note = String(form.get('note') ?? '').trim().slice(0, 120) || null;
		try {
			await setThesis(params.id, on, note);
		} catch {
			return fail(500, { error: 'No se pudo guardar. ¿Has aplicado la migración (python -m lfm.db.migrate)?' });
		}
		return { ok: true };
	},
	// Lista de seguimiento: tus condiciones para que el job te avise. Tampoco toca LaLiga.
	seguir: async ({ params, request }) => {
		const form = await request.formData();
		try {
			if (form.get('off') === '1') {
				await setWatch(params.id, null);
				return { ok: true };
			}
			const parsed = parseWatchForm(form);
			if (!parsed.ok) return fail(400, { watchError: parsed.error });
			await setWatch(params.id, parsed.rule);
		} catch {
			return fail(500, { watchError: 'No se pudo guardar. ¿Has aplicado la migración (python -m lfm.db.migrate)?' });
		}
		return { ok: true };
	}
};
