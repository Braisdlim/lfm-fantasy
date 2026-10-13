/** Demo database names/roles are explicit; an unrelated DATABASE_URL must fail closed. */
export function demoDatabaseUrl(value: string): string {
	const url = new URL(value);
	if (!['postgres:', 'postgresql:'].includes(url.protocol)
		|| url.pathname !== '/lfm_demo' || url.username !== 'lfm_demo') {
		throw new Error('Demo requires the disposable lfm_demo database and role.');
	}
	return value;
}

export function isDemoMutation(method: string): boolean {
	return !['GET', 'HEAD', 'OPTIONS'].includes(method);
}
