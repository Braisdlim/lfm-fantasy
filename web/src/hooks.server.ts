// One private workspace; session signing uses a separate deployment secret.
import type { Handle } from '@sveltejs/kit';
import { redirect } from '@sveltejs/kit';
import { env } from '$env/dynamic/private';
import { dev } from '$app/environment';
import { demoDatabaseUrl, isDemoMutation } from '$lib/server/demo-policy';
import { COOKIE, validAuthSecret, validSession } from '$lib/server/auth';

export const handle: Handle = async ({ event, resolve }) => {
	if (env.DEMO_MODE === 'true') {
		demoDatabaseUrl(env.DATABASE_URL ?? '');
		if (env.DATABASE_TRANSPORT !== 'postgres') return new Response('Invalid demo transport', { status: 503 });
		if (isDemoMutation(event.request.method)) {
			return new Response('La demo es de solo lectura; utiliza una instancia privada para guardar cambios.', { status: 405 });
		}
		return resolve(event);
	}
	if ((!dev || env.APP_PASSWORD) && (!env.APP_PASSWORD || !validAuthSecret(env.AUTH_SECRET))) {
		return new Response('Private deployment requires APP_PASSWORD and a valid AUTH_SECRET', { status: 503 });
	}
	const password = env.APP_PASSWORD;
	const open = event.url.pathname === '/login' || event.url.pathname.startsWith('/manifest') || event.url.pathname === '/service-worker.js';
	if (password && !open && !validSession(event.cookies.get(COOKIE), env.AUTH_SECRET)) {
		redirect(303, '/login');
	}
	return resolve(event);
};
