import { createHmac, randomBytes, timingSafeEqual } from 'node:crypto';

export const COOKIE = 'lfm_auth';
export const SESSION_MAX_AGE = 60 * 60 * 24 * 30;

export function validAuthSecret(secret: string | undefined): secret is string {
	return typeof secret === 'string' && /^[a-fA-F0-9]{64}$/.test(secret);
}

function signature(payload: string, secret: string): string {
	return createHmac('sha256', Buffer.from(secret, 'hex')).update(payload).digest('hex');
}

export function createSession(secret: string, now = Math.floor(Date.now() / 1000)): string {
	if (!validAuthSecret(secret)) throw new Error('AUTH_SECRET must contain 32 random bytes encoded as hex');
	const payload = `v2.${now + SESSION_MAX_AGE}.${randomBytes(16).toString('hex')}`;
	return `${payload}.${signature(payload, secret)}`;
}

export function validSession(value: string | undefined, secret: string | undefined,
	now = Math.floor(Date.now() / 1000)): boolean {
	if (!value || value.length > 256 || !validAuthSecret(secret)) return false;
	const match = /^v2\.(\d{1,12})\.([a-f0-9]{32})\.([a-f0-9]{64})$/.exec(value);
	if (!match || Number(match[1]) <= now) return false;
	const payload = `v2.${match[1]}.${match[2]}`;
	return timingSafeEqual(Buffer.from(match[3], 'hex'), Buffer.from(signature(payload, secret), 'hex'));
}

export function validPassword(given: string, expected: string): boolean {
	if (!expected || given.length > 4096) return false;
	const actual = Buffer.from(given);
	const wanted = Buffer.from(expected);
	return actual.length === wanted.length && timingSafeEqual(actual, wanted);
}
