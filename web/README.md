# Web

SvelteKit 2 / Svelte 5 PWA with TypeScript, Tailwind 4 and ECharts. Backend analysis results are prepared by Python; `src/lib/server/queries.ts` reads them, while the planner evaluates temporary what-if scenarios in the browser.

Start the full-stack demo with real sporting data and an example league from the repository root with `docker compose up --build`, or follow [local development](../docs/setup.md). Private deployment uses Neon HTTP; the local demo uses a restricted PostgreSQL transport.

```bash
npm ci
npm test
npm run check
npm run build
npm run demo:smoke
```

On Windows `build:local` avoids Vercel packaging symlink limitations. The normal production build is checked on Linux in CI. The demo smoke script requires Chromium and a running Compose demo and writes screenshots to `docs/screenshots/` when `CAPTURE_SCREENSHOTS=1`.

Routes: `/`, `/plantilla`, `/mercado`, `/jornada`, `/liga`, `/liga/[teamId]`, `/jugador/[id]`, `/buscar`, `/comparar`, `/planificar`, `/seguimiento`, `/diario`. The web never calls the game API. Demo mutations are rejected at the server boundary, and a private production deployment needs `APP_PASSWORD`.
