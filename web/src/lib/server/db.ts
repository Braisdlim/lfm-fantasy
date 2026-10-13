// Conexión a Neon por HTTP (sin pool): una función por consulta, ideal en serverless.
import { neon } from '@neondatabase/serverless';
import { env } from '$env/dynamic/private';
import { QueryCache } from './query-cache';
import { error } from '@sveltejs/kit';
import { DatabaseAvailability, DatabaseQuotaError } from './database-availability';
import { createHash } from 'node:crypto';
import { demoDatabaseUrl } from './demo-policy';

let localPool: import('pg').Pool | null = null;

/** Local demo transport. Production keeps Neon's HTTP driver and query cache. */
async function query(text: string, params: unknown[]): Promise<Row[]> {
	if (env.DATABASE_TRANSPORT !== 'postgres') return sql().query(text, params as never[]) as Promise<Row[]>;
	const url = demoDatabaseUrl(env.DATABASE_URL ?? '');
	if (!localPool) {
		const { Pool, types } = await import('pg');
		types.setTypeParser(1082, (value) => value);
		localPool = new Pool({ connectionString: url, max: 3, idleTimeoutMillis: 10_000 });
	}
	return (await localPool.query(text, params)).rows;
}

let _sql: ReturnType<typeof neon> | null = null;

export function sql() {
	if (!_sql) {
		const url = env.DATABASE_URL;
		if (!url) throw new Error('DATABASE_URL no configurada');
		_sql = neon(url.replace(/^postgres(ql)?\+\w+:\/\//, 'postgresql://'));
	}
	return _sql;
}

export type Row = Record<string, unknown>;

// Caché en memoria de consultas de lectura para evitar peticiones HTTP redundantes a Neon.
// En serverless/Node, mantiene respuestas durante 20-30s para que la navegación entre pantallas sea instantánea.
const queryCache = new QueryCache();
const availability = new DatabaseAvailability();

/** Limpia la caché en memoria (por ejemplo al mutar datos). */
export function clearQueryCache() {
	queryCache.clear();
}

/** Consulta tipada con caché en memoria de lectura para velocidad nativa. */
export async function q<T = Row>(
	text: string,
	params: unknown[] = [],
	opts: { noCache?: boolean; ttlMs?: number } = {}
): Promise<T[]> {
	const trimmed = text.trimStart().toUpperCase();
	const isReadOnly = (trimmed.startsWith('WITH') || trimmed.startsWith('SELECT'))
		&& !/\b(INSERT|UPDATE|DELETE|MERGE)\b/.test(trimmed);
	const canCache = isReadOnly && !opts.noCache;

	const load = async () => {
		try {
			return await availability.run(async () => {
				const started = performance.now();
				const rows = (await query(text, params)) as T[];
				// Solo descargas reales: no SQL, parámetros, nombres ni valores privados.
				// Tamaño JSON orientativo; el contador facturable lo publica Neon.
				console.info(JSON.stringify({
					event: 'neon_query',
					query: createHash('sha256').update(text).digest('hex').slice(0, 16),
					rows: rows.length,
					json_bytes: Buffer.byteLength(JSON.stringify(rows)),
					ms: Math.round(performance.now() - started)
				}));
				return rows;
			});
		} catch (cause) {
			if (cause instanceof DatabaseQuotaError) {
				error(503, {
					message: cause.message,
					code: 'DATABASE_QUOTA_EXCEEDED'
				});
			}
			throw cause;
		}
	};
	if (!canCache) return load();
	return queryCache.read(`${text}::${JSON.stringify(params)}::${opts.ttlMs ?? 25_000}`, load, opts.ttlMs);
}
