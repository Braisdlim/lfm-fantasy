export type SearchState<T> = { results: T[]; loading: boolean; error: boolean };

/** Búsqueda compartida: espera al escribir y descarta respuestas antiguas. */
export function createPlayerSearch<T>(onChange: (state: SearchState<T>) => void,
	options: { fetch?: typeof fetch; delay?: number } = {}) {
	let timer: ReturnType<typeof setTimeout> | undefined;
	let request: AbortController | undefined;
	let version = 0;
	const cancel = () => { clearTimeout(timer); request?.abort(); version++; };
	return {
		update(term: string, position = 0) {
			cancel();
			const current = version;
			if (term.trim().length < 2) { onChange({ results: [], loading: false, error: false }); return; }
			onChange({ results: [], loading: true, error: false });
			timer = setTimeout(async () => {
				const controller = new AbortController();
				request = controller;
				const params = new URLSearchParams({ q: term.trim() });
				if (position) params.set('pos', String(position));
				try {
					const response = await (options.fetch ?? fetch)(`/api/search?${params}`, { signal: controller.signal });
					if (!response.ok) throw new Error('Search failed');
					const json = await response.json();
					if (current === version) onChange({ results: json.results ?? [], loading: false, error: false });
				} catch {
					if (current === version && !controller.signal.aborted) onChange({ results: [], loading: false, error: true });
				}
			}, options.delay ?? 250);
		},
		reset() { cancel(); onChange({ results: [], loading: false, error: false }); },
		destroy: cancel
	};
}
