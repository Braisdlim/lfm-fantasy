/// <reference types="@sveltejs/kit" />
/// <reference no-default-lib="true"/>
/// <reference lib="esnext" />
/// <reference lib="webworker" />
// Shell cacheado (assets de build + estáticos); las páginas van por red y, sin red, a caché.
import { build, files, version } from '$service-worker';

const sw = self as unknown as ServiceWorkerGlobalScope;
const CACHE = `lfm-${version}`;
const ASSETS = [...build, ...files];

sw.addEventListener('install', (event) => {
	event.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => sw.skipWaiting()));
});

sw.addEventListener('activate', (event) => {
	event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => sw.clients.claim()));
});

sw.addEventListener('fetch', (event) => {
	const { request } = event;
	if (request.method !== 'GET') return;
	const url = new URL(request.url);
	if (url.origin !== location.origin) return;
	if (ASSETS.includes(url.pathname)) {
		event.respondWith(caches.open(CACHE).then((c) => c.match(request).then((r) => r ?? fetch(request))));
		return;
	}
	event.respondWith(
		fetch(request)
			.then((res) => {
				if (res.ok && request.mode === 'navigate') caches.open(CACHE).then((c) => c.put(request, res.clone()));
				return res;
			})
			.catch(() => caches.match(request).then((r) => r ?? new Response('Sin conexión', { status: 503 })))
	);
});
