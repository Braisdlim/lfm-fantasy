# A quota incident as an engineering case study

## Problem

The private application became unavailable after its database provider's monthly transfer allowance was exhausted. The relevant bottleneck was data leaving PostgreSQL, not simply the number of page requests. Repeated wide historical queries and recomputation made light collection more expensive than expected.

## Changes

1. Read compact current records while preserving historical source evidence.
2. Batch journal enrichment instead of issuing repeated per-player reads.
3. Persist trained price-model results with date, input and code fingerprints. Reuse them only after verifying that the inputs still match.
4. Store full HTML as compressed deduplicated payloads rather than discard evidence needed to repair parsers.
5. Coalesce concurrent web reads, use a short cache and stop repeated requests during a known quota suspension.
6. Check provider metrics before scheduled work, retaining headroom below provider limits; fail closed when required budget data is unavailable.
7. Back up portable non-token data and prove recovery by restoring into isolated PostgreSQL, rather than merely checking that an archive exists.

## Observations from bounded samples

| Check | Before | After | Scope |
| --- | --- | --- | --- |
| Journal enrichment | 436 SQL queries, ~20.7 s | 6 SQL queries, ~0.48 s | Same 63 output rows in one private snapshot |
| Suggested-lineup refresh | ~178 KB of SQL output | ~55 KB, 9 queries, ~0.41 s | Same positional baselines; scoped own-player history |
| Cached recommendation plus lineup phase | Repeated model input/training | ~0.531 MB SQL output | One warm persistent-cache sample |

These observations are not load-test percentiles or a fixed monthly cost guarantee. Cold processes, changing histories and additional users can change consumption. Provider metrics remain the billable source of truth.

## Correctness found during optimisation

The UI said “next gameweek” while one calculation included two weeks. The audit corrected the horizon, kept the scoring weights, and added regression coverage. It also moved lineup refresh into the light job and combined official and external availability. Optimising only bytes would have missed this product bug.

## Remaining constraints

The web cache is local to each process, history grows, source schemas can change and a free tier has a hard cap. Budget guards protect the jobs they precede; they do not make every web read globally quota-proof. A multi-user version needs shared ingestion, tenant scoping and separate load/consumption tests.
