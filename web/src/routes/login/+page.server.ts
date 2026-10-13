import { fail, redirect } from '@sveltejs/kit';
import { env } from '$env/dynamic/private';
import { COOKIE, SESSION_MAX_AGE, createSession, validAuthSecret, validPassword, validSession } from '$lib/server/auth';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = ({ cookies }) => {
	const password = env.APP_PASSWORD;
	if (!password || validSession(cookies.get(COOKIE), env.AUTH_SECRET)) redirect(303, '/');
	return {};
};

export const actions: Actions = {
	default: async ({ request, cookies, url }) => {
		const data = await request.formData();
		const given = String(data.get('password') ?? '');
		const password = env.APP_PASSWORD ?? '';
		if (!validPassword(given, password)) return fail(401, { wrong: true });
		if (!validAuthSecret(env.AUTH_SECRET)) return fail(503, { wrong: true });
		cookies.set(COOKIE, createSession(env.AUTH_SECRET), {
			path: '/',
			httpOnly: true,
			sameSite: 'lax',
			secure: url.protocol === 'https:',
			maxAge: SESSION_MAX_AGE
		});
		redirect(303, '/');
	}
};
