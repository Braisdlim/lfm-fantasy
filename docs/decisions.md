# Architecture decisions

These notes describe decisions implemented in the current code. They were recorded retrospectively for the public edition on 13 October 2026; they are not invented historical design records.

## 1. Prepare decisions in Python; read results in the web

**Context.** Historical data is useful for recommendations but expensive to repeatedly transfer and analyse during page requests.

**Decision.** Scheduled Python jobs store recommendations, reasons, forecasts and lineups in PostgreSQL. SvelteKit reads prepared results. A short process-local cache coalesces identical reads. The transfer planner performs its bounded what-if calculation in the browser.

**Alternatives.** Recalculate the complete model on every request, or introduce a queue and separate analysis service. The first repeats database cost; the second adds infrastructure the single-owner workload does not yet justify.

**Trade-off.** Results can be stale between successful jobs. Source timestamps and job status must remain visible. A process-local cache cannot guarantee a global transfer budget across cold serverless instances.

**Evidence.** [Light job](../src/lfm/jobs/light.py), [queries](../web/src/lib/server/queries.ts), [cache concurrency tests](../web/tests/query-cache.test.ts).

## 2. Commit collected evidence before analysis

**Context.** Unofficial APIs and external HTML can change. A calculation can fail after a valid source response has already been collected.

**Decision.** Preserve raw evidence, normalise it, and commit collection separately from analysis. Keep analysis failures observable and allow independent steps to continue.

**Alternatives.** One transaction for the whole job, or retaining only normalised rows. The first can discard useful observations; the second makes parser investigation and reprocessing harder.

**Trade-off.** Raw evidence needs storage and careful access control. Different outputs can reflect different successful refreshes; transactional boundaries do not mean every screen is an atomic snapshot of the whole system.

**Evidence.** [Raw payload storage](../src/lfm/db/raw_payload.py), [failure-isolation tests](../tests/test_light.py), [backup round-trip test](../tests/test_backup.py).

## 3. Verify persistent caches against source changes

**Context.** The same historical rows were being transferred and models recomputed repeatedly, but a date alone cannot detect a corrected past price.

**Decision.** Verify source fingerprints before reusing the local price history and persisted model outputs. Code/input/date fingerprints invalidate derived results as needed.

**Alternatives.** A time-only expiry is simpler but may silently reuse corrected data. Always recomputing is simpler for correctness but repeatedly consumes transfer and CPU.

**Trade-off.** Fingerprinting still costs database work. A failed verification cannot safely become a cache hit. Checks and content must agree under concurrent writes.

**Evidence.** [Price cache](../src/lfm/db/price_cache.py), [analysis cache](../src/lfm/db/analysis_cache.py), [correction and race tests](../tests/test_price_cache.py), [model cache tests](../tests/test_analysis_cache.py).

## 4. Keep the public demo reproducible and isolated

**Context.** A reviewer should run the product without a game account, a production password or a billable database connection.

**Decision.** Bundle an allowlist of real public sports records with fixed dates; create an explicitly fictional league; run the actual analysis against disposable PostgreSQL. Reject web mutations and require a dedicated demo database and role.

**Alternatives.** A live shared production login exposes private data and consumption. Entirely fabricated sports records obscure the real domain. Screenshots alone cannot prove the application starts.

**Trade-off.** The snapshot ages and covers only 64 selected players. Illustrative league transactions are not valid evidence for real bidding performance. The demo does not demonstrate multi-tenant authorisation.

**Evidence.** [Publication boundary](publication.md), [seed](../src/lfm/demo.py), [Compose](../compose.yaml), [browser smoke](../web/scripts/demo-smoke.mjs).

## What would change next

| Trigger | Next change | Acceptance evidence |
| --- | --- | --- |
| Independent people share one deployment | Tenant-aware schema, authentication, query/cache/model boundaries | Cross-tenant access tests and migration/rollback exercise |
| Recommendations are presented as predictively effective | Time-ordered holdout evaluation against simple baselines | Versioned inputs, leakage checks and out-of-sample results |
| More concurrent users or tighter database limits | Measure representative traffic; consider shared cache and bounded read budgets | Reproducible cold/warm load tests with provider transfer metrics |

These are proposals, not completed features. Their priority depends on a real requirement; adding infrastructure solely to enlarge the stack is not a goal.
