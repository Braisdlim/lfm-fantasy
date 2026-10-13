// Reloj puntual para lfm.
//
// El problema: el cron de GitHub Actions mete las tareas programadas en la misma cola que todos los
// push del planeta. Medido en este repo el 2026-09-08: el job diario previsto a las 18:30 arrancó a
// las 21:18 (+169 min), y de catorce disparos horarios del job ligero llegaron dos.
//
// La solución no es cambiar de obrero: Actions ejecuta bien, tiene el entorno de Python y guarda los
// secretos. Lo que hace mal es de reloj. Así que este Worker se limita a ser el reloj y le pide a
// Actions que trabaje con `workflow_dispatch`, que **no pasa por esa cola**: medido, arranca en unos
// 15 segundos. Reloj puntual + 15 s + 40 s de job = menos de dos minutos de punta a punta.
//
// Solo dispara en los dos momentos que deciden (ver src/schedule.js). El resto del día lo cubre el
// cron de GitHub, al que no le pedimos puntualidad porque no la tiene.

import { jobFor, madridTime, planFor } from './schedule.js';

const API = 'https://api.github.com';

const madridHHMM = (d) => {
  const { hour, minute } = madridTime(d);
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
};

export async function dispatch(job, env, { skipIfRecent = false } = {}) {
  const url = `${API}/repos/${env.REPO}/actions/workflows/${env.WORKFLOW || 'collect.yml'}/dispatches`;
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'User-Agent': 'lfm-trigger',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      ref: env.BRANCH || 'main',
      inputs: { job, skip_if_recent: skipIfRecent ? 'true' : 'false' },
    }),
  });
  // La API responde 204 sin cuerpo cuando acepta el disparo.
  if (res.status !== 204) {
    throw new Error(`GitHub respondió ${res.status}: ${(await res.text()).slice(0, 300)}`);
  }
  return job;
}

export default {
  async scheduled(event, env, ctx) {
    const ahora = new Date(event.scheduledTime);
    const plan = planFor(ahora);
    const job = plan?.job ?? null;
    // Se registra **cada** despertar, aunque no toque nada. Es lo único que permite distinguir
    // "el reloj se ha parado" de "el reloj funciona y no tocaba", y los crones de Cloudflare
    // también pueden dejar de dispararse en silencio (`wrangler tail` para verlo en vivo).
    console.log(`despierta ${madridHHMM(ahora)} Madrid -> ${job ? `${job}${plan.skipIfRecent ? ' (si no está hecho)' : ''}` : 'nada que hacer'}`);
    if (!job) return;
    ctx.waitUntil(
      dispatch(job, env, { skipIfRecent: plan.skipIfRecent }).then(
        () => console.log(`disparado ${job}`),
        (e) => console.error(`no se pudo disparar ${job}: ${e.message}`),
      ),
    );
  },

  // Para comprobar a mano que el token y los permisos funcionan, sin esperar a la ventana:
  //   curl "https://<worker>.workers.dev/?job=light&key=<TRIGGER_KEY>"
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === '/health') {
      return Response.json({ ok: true, ahora: jobFor(new Date()) ?? 'fuera de ventana' });
    }
    if (!env.TRIGGER_KEY || url.searchParams.get('key') !== env.TRIGGER_KEY) {
      return new Response('no autorizado', { status: 401 });
    }
    const job = url.searchParams.get('job');
    if (job !== 'light' && job !== 'daily') {
      return new Response('usa ?job=light o ?job=daily', { status: 400 });
    }
    try {
      await dispatch(job, env);
      return Response.json({ disparado: job });
    } catch (e) {
      return Response.json({ error: e.message }, { status: 502 });
    }
  },
};
