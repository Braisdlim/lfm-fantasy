/** Agrupa lecturas simultáneas y descarta respuestas anteriores a una invalidación. */
export class QueryCache {
	private entries = new Map<string, { data: unknown[]; expires: number }>();
	private pending = new Map<string, Promise<unknown[]>>();
	private generation = 0;

	clear() {
		this.generation++;
		this.entries.clear();
		this.pending.clear();
	}

	async read<T>(key: string, load: () => Promise<T[]>, ttlMs = 25_000): Promise<T[]> {
		const cached = this.entries.get(key);
		if (cached && cached.expires > Date.now()) return cached.data as T[];
		const pending = this.pending.get(key);
		if (pending) return pending as Promise<T[]>;
		const generation = this.generation;
		const request = Promise.resolve().then(load);
		this.pending.set(key, request);
		try {
			const data = await request;
			if (generation === this.generation) {
				if (this.entries.size >= 250) {
					for (const key of Array.from(this.entries.keys()).slice(0, 50)) this.entries.delete(key);
				}
				this.entries.set(key, { data, expires: Date.now() + ttlMs });
			}
			return data;
		} finally {
			if (this.pending.get(key) === request) this.pending.delete(key);
		}
	}
}
