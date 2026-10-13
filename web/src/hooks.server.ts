// Acceso de un solo usuario: si APP_PASSWORD está definida, exige una cookie firmada.
// Sin sistema de usuarios (docs/estrategia.md §5.3): una clave, una cookie, un año.
import { createHmac } from 'node:crypto';
import type { Handle } from '@sveltejs/kit';
import { redirect } from '@sveltejs/kit';
import { env } from '$env/dynamic/private';
import { dev } from '$app/environment';
import { demoDatabaseUrl, isDemoMutation } from '$lib/server/demo-policy';

export const COOKIE = 'lfm_auth';

export function token(password: string): string {
	return createHmac('sha256', 'lfm-auth-v1').update(password).digest('hex');
}

export const handle: Handle = async ({ event, resolve }) => {
	if (env.DEMO_MODE === 'true') {
		demoDatabaseUrl(env.DATABASE_URL ?? '');
		if (env.DATABASE_TRANSPORT !== 'postgres') return new Response('Invalid demo transport', { status: 503 });
		if (isDemoMutation(event.request.method)) {
			return new Response('La demo es de solo lectura; utiliza una instancia privada para guardar cambios.', { status: 405 });
		}
	} else if (!dev && !env.APP_PASSWORD) {
		return new Response('Private deployment requires APP_PASSWORD', { status: 503 });
	}
	const password = env.APP_PASSWORD;
	const open = event.url.pathname === '/login' || event.url.pathname.startsWith('/manifest') || event.url.pathname === '/service-worker.js';
	if (password && !open && event.cookies.get(COOKIE) !== token(password)) {
		redirect(303, '/login');
	}
	return resolve(event);
};
