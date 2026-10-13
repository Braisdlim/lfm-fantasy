# A private live deployment

The public repository is a portfolio/demo, not a shared live sports service. Keep an operational copy private: collector logs, backups and raw captures can contain private league data even when GitHub secrets themselves are protected.

## Components

| Component | Deployment used by the original private app | Responsibility |
| --- | --- | --- |
| Python jobs | GitHub Actions on Linux | Read-only ingestion and prepared analysis |
| PostgreSQL | Neon, PostgreSQL 17 | Evidence, time series, models and private league state |
| PWA | Vercel, root directory `web` | SSR and read queries via Neon HTTP |
| Optional trigger | Cloudflare Worker | Dispatch jobs within league reset windows |
| Optional notifications | Telegram bot | Send a private decision summary |

## Bootstrap

1. Create a **private repository** for the live deployment from the reviewed code, without demo credentials.
2. Provision a separate PostgreSQL/Neon database. Configure the provider's quota limits/headroom and a budget-read API credential if using `jobs/neon_budget.py`.
3. `uv sync --frozen`, copy `.env.example` to an ignored local `.env`, and fill the private connection URL.
4. Run `uv run python -m lfm.db.migrate` against that new database. Back up first when applying migrations to an existing instance.
5. Authenticate your own game account with `uv run python -m lfm.api.auth login` or `login-google`. The latter uses an interactive PKCE flow. Keep `.tokens.json` private. `whoami` verifies access; set the actual `LEAGUE_ID`.
6. Run one daily collection and inspect `job_runs.summary`, coverage and source timestamps. A top-level `ok` does not prove every optional analysis step succeeded.
7. Deploy `web/` to Vercel with `DATABASE_URL` and a strong `APP_PASSWORD`. Leave `DEMO_MODE` and `DATABASE_TRANSPORT` unset: the live web uses Neon HTTP. Production without a password fails closed in this public edition.

API access is unofficial. Source endpoints and authentication can change; verify your account's access and applicable provider rules. This repository is not affiliated with LaLiga or its data sources.

## Configuration boundaries

| Value | Where | Notes |
| --- | --- | --- |
| `DATABASE_URL` | private backend and web secrets | Use the relevant instance only; never print it |
| `LALIGA_REFRESH_TOKEN` | private job secret | Bootstraps the collector; rotated tokens can be stored in `auth_tokens` |
| `LEAGUE_ID` | private job configuration | Selects that owner's league |
| `APP_PASSWORD` | private web secret | One shared workspace, not separate accounts |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | optional private job secrets | Without them notifications are printed locally |
| `APP_URL` | optional private job variable | Your deployed web URL for alert links; blank means no links |
| `PRICE_CACHE_DIR` | job configuration | Optional validated disk copy; avoid caching credentials/raw league captures |
| `NEON_API_KEY`, `NEON_PROJECT_ID` | budget-check step | Required for the provider metric guard |

Use secret stores or stdin; avoid putting real tokens on a command line, in screenshots or in tickets. The example `.env` is intentionally placeholders only.

## Scheduling

The example [private collector workflow](../.github/workflows/collect.yml) is manual and gated by **both** a private repository and `ENABLE_COLLECTION=true`. It does nothing on this public repository. Configure its secrets, provider quota values and `NEON_PROJECT_ID`, then enable it in your private copy.

The included budget policy expects provider caps at most **4 GB transfer, 80 CU-hours and 900 MB logical storage**, and stops new collection at **3.5 GB, 70 CU-hours or 800 MB reported storage**. These are this project's conservative policy, not a statement of the provider's current plan allowances. Review the constants in `neon_budget.py`, provider metrics and your plan before enabling collection.

For ongoing use, schedule the daily job after your league's market reset and the light job only in useful windows. GitHub cron can be delayed or skipped; deduplicate attempts using `--skip-if-recent`. Match league timezone/DST and budget actual requests, rather than assuming all leagues share the original reset time.

The optional `trigger/` Worker is a scheduling example. Change `REPO`, window logic and credentials before deployment. Its token should be restricted to dispatching Actions in the private operational repository.

## Operations and recovery

- Collection commits before analysis; analyse step-specific errors instead of discarding a good captured snapshot.
- Inspect source freshness, `collect_errors`, model errors and backup restore results.
- Provider metrics are the billing source of truth. The guard checks configured caps and current-period usage and fails closed if it cannot verify them. It only protects work that passes through that step.
- `python -m lfm.db.backup` produces a portable archive excluding authentication tokens. **It can still contain personal league data.** Keep it in private storage, define retention and prove restoration into a disposable database.
- Token loss/expiry needs a new interactive login. Backups without `auth_tokens` do not recreate that session.
- Changes to global user scope require the work described in [adding users](users.md), not just another password.
