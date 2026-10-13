# Code and test guide

Start with one behaviour and follow its implementation into a regression test. The [architecture](architecture.md) gives the wider context; the [screenshots](walkthrough.md) show the resulting product.

## 1. Database efficiency without changing the result

Read [`enrich_many` in the journal](../src/lfm/analysis/journal.py) and its [PostgreSQL test](../tests/test_journal_batch.py). The test compares batch enrichment with the individual path, including missing players, missing points, mixed price sources and repeated holdings. Four and 200 holdings both require six batched reads; empty input performs none.

The [incident case study](engineering.md) separates this reproducible check from timings observed on one private snapshot. For cache correctness, [price-cache tests](../tests/test_price_cache.py) cover corrections, deletions, concurrent changes and corrupt files.

## 2. Domain constraints and incomplete data

Read [lineup selection](../src/lfm/analysis/eleven.py) with its [tests](../tests/test_eleven.py): legal formations, injured players, missing goalkeepers and infeasible squads. The [points regression](../tests/test_fixtures_points.py) prevents a second future fixture inflating a next-gameweek estimate.

These are rules and correctness checks. [The model contract](criterio.md) explains statistical assumptions and the evaluation still needed to establish predictive performance.

## 3. Failure boundaries

Read the [light job](../src/lfm/jobs/light.py) with its [orchestration tests](../tests/test_light.py). Collection survives a failed analysis step. In the web, [query-cache tests](../web/tests/query-cache.test.ts) cover concurrent requests, retry and invalidation while an old request is still in flight.

For an example of a security fix, [PR #5](https://github.com/Braisdlim/lfm-fantasy/pull/5) replaces password-derived cookies with independently signed, expiring sessions. [Unit tests](../web/tests/auth.test.ts) and an [HTTP login smoke test](../web/scripts/auth-smoke.mjs) verify the boundary.

## Run and inspect

The [local demo](../README.md#try-it-locally) requires no credentials. [Test instructions](setup.md#tests) cover both database-free checks and disposable PostgreSQL integration tests.

[CI](https://github.com/Braisdlim/lfm-fantasy/actions/workflows/ci.yml) checks Python/SQL, web types and build, scheduler logic, authentication and the 13-route Compose demo. The `python-verification` artifact contains JUnit results and HTML branch coverage, retained for 14 days. [CodeQL](https://github.com/Braisdlim/lfm-fantasy/actions/workflows/codeql.yml) provides static security analysis. These checks establish specific behaviours; coverage and passing scans are not evidence of forecast accuracy or the absence of all defects.

## Project context

Brais's personal project, developed with AI assistance for implementation, investigation and documentation. The public edition has a curated Git history to keep private operational data out of the repository. Current scope and future design constraints are recorded in [decision notes](decisions.md).

Operational details are secondary references: [hosting and configuration](deployment.md), [ownership boundary](users.md), [data provenance and rights](publication.md), and [security](../SECURITY.md).
