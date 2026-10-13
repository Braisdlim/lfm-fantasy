// Una cuota agotada no se resuelve repitiendo cada consulta de cada pantalla.
export class DatabaseQuotaError extends Error {
	constructor() {
		super('La base de datos está suspendida porque Neon ha agotado una cuota.');
		this.name = 'DatabaseQuotaError';
	}
}

export function isDatabaseQuotaError(value: unknown): boolean {
	return value instanceof Error &&
		/\b(?:account or project has exceeded (?:the |its )?(?:compute time |data transfer )?quota|quota (?:has been )?exceeded)\b/i.test(value.message);
}

export class DatabaseAvailability {
	private blockedUntil = 0;
	private now: () => number;
	private cooldownMs: number;

	constructor(now = Date.now, cooldownMs = 60_000) {
		this.now = now;
		this.cooldownMs = cooldownMs;
	}

	async run<T>(load: () => Promise<T>): Promise<T> {
		if (this.now() < this.blockedUntil) throw new DatabaseQuotaError();
		try {
			return await load();
		} catch (cause) {
			if (!isDatabaseQuotaError(cause)) throw cause;
			this.blockedUntil = this.now() + this.cooldownMs;
			throw new DatabaseQuotaError();
		}
	}
}
