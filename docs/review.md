# A five-minute technical review

LFM is a personal tool for deciding which fantasy football players to buy, what to bid and who to field. The interesting engineering problem is turning incomplete, changing data into useful decisions within a small database budget.

**Start without credentials:** follow the [Docker quickstart](../README.md#try-it-locally), or browse the [six actual screenshots](walkthrough.md). The UI is in Spanish; this guide and the architecture documentation are in English. The bundled sports data is real and dated; the league is illustrative.

## Pick a path

| Time | Read | What to look for |
| --- | --- | --- |
| 1 minute | [Product walkthrough](walkthrough.md) | Recommendations, lineup and transfer simulation; visible uncertainty |
| 3 minutes | [Architecture](architecture.md) and [decisions](decisions.md) | Transaction boundaries, prepared results, cache scope and alternatives |
| 5 minutes | One implementation/test pair below | A concrete behaviour and a regression test you can run |
| Deeper review | [Quota incident](engineering.md) and [model contract](criterio.md) | What was measured, what was corrected and what remains unproven |

## Follow a claim into the code

| Claim | Implementation | Executable evidence |
| --- | --- | --- |
| Journal enrichment avoids per-holding query growth | [`enrich_many`](../src/lfm/analysis/journal.py), [batched reads](../src/lfm/db/batch_reads.py) | [PostgreSQL regression](../tests/test_journal_batch.py): equal output to the individual path, six reads for both 4 and 200 holdings |
| Cache reuse requires checking the actual source history | [Price cache](../src/lfm/db/price_cache.py) | [Cache tests](../tests/test_price_cache.py): corrections, deletions, concurrent changes and corrupt files |
| An unavailable player cannot enter the suggested eleven | [Lineup selection](../src/lfm/analysis/eleven.py) | [Lineup tests](../tests/test_eleven.py): legal formations, injuries, suspensions and infeasible squads |
| “Next gameweek” means one gameweek | [Expected points](../src/lfm/analysis/points.py) | [Horizon regression](../tests/test_fixtures_points.py): a second fixture cannot inflate the next-gameweek estimate |
| Failed analysis does not discard a newly collected market | [Light job](../src/lfm/jobs/light.py) | [Orchestration tests](../tests/test_light.py): failures recorded while collection and other analysis survive |
| Concurrent identical page reads share work | [Query cache](../web/src/lib/server/query-cache.ts) | [Web tests](../web/tests/query-cache.test.ts): coalescing, expiry, retry and stale-response invalidation |
| The public demo has an explicit data boundary | [Seed](../src/lfm/demo.py), [request hook](../web/src/hooks.server.ts) | [Python policy](../tests/test_demo.py), [web policy](../web/tests/demo-policy.test.ts), [browser smoke](../web/scripts/demo-smoke.mjs) |

For a small first check, run `uv sync --locked` then `uv run pytest -q tests/test_eleven.py tests/test_fixtures_points.py`. These tests do not need a database or sports credentials. PostgreSQL tests require a separate disposable test database; see [setup](setup.md#tests).

## What the checks establish

[CI](https://github.com/Braisdlim/lfm-fantasy/actions/workflows/ci.yml) runs the Python suite against disposable PostgreSQL, TypeScript/trigger tests, Svelte diagnostics, a production build, secret scanning and the Compose browser smoke. The Python job publishes a JUnit report and an HTML branch-coverage report for 14 days. Coverage identifies unexercised code; it does not establish forecast accuracy. Browse the report rather than interpreting a green badge as complete test coverage.

[CodeQL](https://github.com/Braisdlim/lfm-fantasy/actions/workflows/codeql.yml) analyses Python and JavaScript/TypeScript. Static scanning complements the tests and is not a security certification.

The journal regression is reproducible in public CI. The timings in the incident case study came from one private snapshot and cannot be reproduced exactly from the different demo dataset. There is no published production-scale load test or out-of-sample forecast-accuracy claim.

## Ownership and scope

This is Brais's personal project, with AI-assisted implementation, investigation and documentation. The public edition has a fresh, curated history so private operational data is not exposed. It is not a record of team delivery or a claim that every line was written unaided. The implementation, tests and stated limitations are available for review.

The application currently serves one owner. Independent accounts, tenant isolation and model evaluation on held-out future results are [future work](decisions.md#what-would-change-next). Public visibility does not grant an open-source licence; see [publication terms and data provenance](publication.md).
