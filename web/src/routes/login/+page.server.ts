import { fail, redirect } from '@sveltejs/kit';
import { env } from '$env/dynamic/private';
import { COOKIE, token } from '../../hooks.server';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = ({ cookies }) => {
	const password = env.APP_PASSWORD;
	if (!password || cookies.get(COOKIE) === token(password)) redirect(303, '/');
	return {};
};

export const actions: Actions = {
	default: async ({ request, cookies, url }) => {
		const data = await request.formData();
		const given = String(data.get('password') ?? '');
		const password = env.APP_PASSWORD ?? '';
		if (!password || given !== password) return fail(401, { wrong: true });
		cookies.set(COOKIE, token(password), {
			path: '/',
			httpOnly: true,
			sameSite: 'lax',
			secure: url.protocol === 'https:',
			maxAge: 60 * 60 * 24 * 365
		});
		redirect(303, '/');
	}
};
