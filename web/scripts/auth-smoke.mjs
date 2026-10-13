import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { once } from 'node:events';
import { createServer } from 'node:net';

async function withServer(secret, check) {
	const reservation = createServer();
	reservation.listen(0, '127.0.0.1');
	await once(reservation, 'listening');
	const port = reservation.address().port;
	await new Promise((resolve) => reservation.close(resolve));
	const base = `http://127.0.0.1:${port}`;
	const child = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], {
		env: { ...process.env, APP_PASSWORD: 'disposable-login-test', AUTH_SECRET: secret, DEMO_MODE: 'false',
			DATABASE_URL: 'postgresql://unused:unused@127.0.0.1:1/unused', DATABASE_TRANSPORT: 'postgres' },
		stdio: 'ignore'
	});
	const exited = once(child, 'exit');
	try {
		let ready = false;
		for (let attempt = 0; attempt < 100; attempt++) {
			try {
				const response = await fetch(`${base}/login`, { redirect: 'manual', signal: AbortSignal.timeout(2000) });
				if ([200, 503].includes(response.status)) { ready = true; break; }
			} catch { /* Wait for the local test server. */ }
			if (child.exitCode !== null) throw new Error('Auth test server exited early');
			await new Promise((resolve) => setTimeout(resolve, 300));
		}
		assert.ok(ready, 'auth test server starts');
		await check(base);
	} finally {
		child.kill();
		await exited;
	}
}

await withServer(randomBytes(32).toString('hex'), async (base) => {
	const anonymous = await fetch(base, { redirect: 'manual' });
	assert.equal(anonymous.status, 303);
	assert.equal(anonymous.headers.get('location'), '/login');
	const login = (password) => fetch(`${base}/login`, { method: 'POST', redirect: 'manual',
		headers: { origin: base, accept: 'text/html' }, body: new URLSearchParams({ password }) });
	assert.equal((await login('wrong')).status, 401);
	const signedIn = await login('disposable-login-test');
	assert.equal(signedIn.status, 303);
	const cookie = signedIn.headers.get('set-cookie');
	assert.match(cookie, /HttpOnly/i);
	assert.match(cookie, /SameSite=Lax/i);
	assert.match(cookie, /Max-Age=2592000/i);
	const returning = await fetch(`${base}/login`, { redirect: 'manual', headers: { cookie: cookie.split(';')[0] } });
	assert.equal(returning.status, 303);
	assert.equal(returning.headers.get('location'), '/');
	const tampered = await fetch(base, { redirect: 'manual', headers: { cookie: 'lfm_auth=invalid' } });
	assert.equal(tampered.status, 303);
	assert.equal(tampered.headers.get('location'), '/login');
});

await withServer('', async (base) => {
	assert.equal((await fetch(base, { redirect: 'manual' })).status, 503);
});

console.log('Auth HTTP smoke passed: redirect, login, cookie policy, tampering and missing-secret rejection. No database required.');
