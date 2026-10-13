# Local setup

## Recommended: isolated demo

Requirements: Docker engine and Docker Compose v2. On Windows, start Docker Desktop with Linux containers. On macOS/Linux, use the corresponding Docker installation. No sports account is required.

```bash
docker compose up --build
```

Open http://localhost:5173. Wait until `seed` exits with code 0 and `web` reports the Vite server address. Ports are bound to the local machine only. PostgreSQL is available on localhost:55432 with database, role and password `lfm_demo`; these are disposable demo credentials.

```bash
docker compose ps -a
docker compose logs seed
docker compose logs web
docker compose stop
```

### Refresh the demo

The sports snapshot is fixed at 13 October 2026. The example league's market expiry is generated once, so a persisted snapshot ages honestly. To discard **only the local Compose demo** and recreate the example league:

```bash
docker compose down --volumes
docker compose up --build
```

The first command deletes the local demo volume. Do not run it in a production Compose project. Rebuilding does not change the real snapshot's sporting dates or refresh prices. Alternatively change the Compose project name and ports to create an independent demo without deleting an existing one.

## Develop without running the web in Docker

Use Python 3.12+, `uv`, Node 24 and npm. Keep the Compose database and seed:

```bash
docker compose up database seed
uv sync --frozen
cd web
npm ci
```

Create `web/.env` locally:

```dotenv
DATABASE_URL=postgresql://lfm_demo:lfm_demo@localhost:55432/lfm_demo
DATABASE_TRANSPORT=postgres
DEMO_MODE=true
```

```bash
npm run dev
```

Do not copy the private production `.env` into this public edition. For a live private deployment see [deployment](deployment.md).

## Tests

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
cd web
npm test
npm run check
npm run build:local
npm run demo:smoke
```

The smoke command requires the demo at localhost:5173 and Playwright Chromium (`npx playwright install chromium`). It exercises routes, search, planner and read-only protection and captures the real UI. Without `TEST_POSTGRES_URL`, the separate PostgreSQL integration tests are skipped. CI provides its own disposable PostgreSQL test database.

For a local branch-coverage report, run `uv run pytest --cov --cov-report=html:reports/coverage` and open `reports/coverage/index.html`. Without PostgreSQL, the report excludes the skipped integration paths. CI uploads its full run as the `python-verification` artifact, together with JUnit results; reports are retained for 14 days. `uv run python scripts/check_docs.py` checks tracked documentation's relative links and heading anchors without contacting external sites.

## Troubleshooting

- **Port already in use:** stop the other local server or change the published Compose port and set `DEMO_URL` for the smoke script.
- **Docker daemon unavailable:** start Docker Desktop; `docker compose config` alone does not start the engine.
- **`seed` failed:** read its logs before proceeding. The web waits for a successful seed, and its transaction does not mark partial data as ready.
- **Old sport dates:** this is a dated real snapshot, not a live service. A reviewed replacement dataset is needed for newer sports data. Recreating the volume only renews the example league's clock.
- **Windows npm execution policy:** use `npm.cmd` instead of `npm`.
- **Vercel adapter symlink error on Windows:** `npm run build:local` validates the client/server build; CI validates the normal Linux production package.
