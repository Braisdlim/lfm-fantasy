import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createSession, SESSION_MAX_AGE, validAuthSecret, validPassword, validSession } from '../src/lib/server/auth.ts';

const secret = 'ab'.repeat(32); // Disposable test key, never deployment configuration.

test('sessions have independent random nonces and validate with the signing key', () => {
	const first = createSession(secret, 1000);
	assert.notEqual(first, createSession(secret, 1000));
	assert.ok(validSession(first, secret, 1001));
});

test('tampering with expiry, nonce or signature is rejected', () => {
	const token = createSession(secret, 1000);
	for (const index of [1, 2, 3]) {
		const parts = token.split('.');
		parts[index] = parts[index].startsWith('1') ? `2${parts[index].slice(1)}` : `1${parts[index].slice(1)}`;
		assert.equal(validSession(parts.join('.'), secret, 1001), false);
	}
});

test('server expiration applies even when a browser sends an expired cookie', () => {
	const token = createSession(secret, 1000);
	assert.ok(validSession(token, secret, 1000 + SESSION_MAX_AGE - 1));
	assert.equal(validSession(token, secret, 1000 + SESSION_MAX_AGE), false);
});

test('rotating the independent secret invalidates existing sessions', () => {
	assert.equal(validSession(createSession(secret, 1000), 'cd'.repeat(32), 1001), false);
});

test('malformed or legacy cookies and invalid configuration fail closed', () => {
	for (const value of [undefined, '', 'a'.repeat(64), 'v2.1.x.y', 'v2.9999999999999.x.y', 'x'.repeat(300)]) {
		assert.equal(validSession(value, secret, 1000), false);
	}
	for (const key of [undefined, '', 'too-short', 'z'.repeat(64)]) {
		assert.equal(validAuthSecret(key), false);
		assert.equal(validSession(createSession(secret, 1000), key, 1001), false);
	}
	assert.throws(() => createSession('short'));
});

test('password comparison handles Unicode, unequal lengths and empty configuration', () => {
	assert.ok(validPassword('contraseña de prueba', 'contraseña de prueba'));
	assert.equal(validPassword('contraseña de pruebb', 'contraseña de prueba'), false);
	assert.equal(validPassword('short', 'a longer password'), false);
	assert.equal(validPassword('', ''), false);
	assert.equal(validPassword('a'.repeat(4097), 'a'.repeat(4097)), false);
});
