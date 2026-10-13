# Ownership boundary

LFM currently serves one owner and one selected league per database. A shared password gives access to the same workspace. There is no account registration or tenant isolation.

The own team is selected through `league_teams.is_me`; watchlists, several reads and model/cache scopes assume that single owner. [Private sessions](../web/src/lib/server/auth.ts) authenticate access to this workspace. They do not authorise independent accounts against separate records.

## Why this matters

Adding a second login would not isolate data. A shared service would require owner keys and server-side ownership checks across queries, mutations, caches, jobs, game credentials and notification destinations. Cross-user read/write tests would need to cover forged IDs and cache collisions. That is a separate architectural change.

Separate infrastructure can isolate owners, but it duplicates collection and storage. The [operational reference](deployment.md) describes the current deployment pattern; onboarding an unrelated account has not been validated end to end.

The public demo is the supported review path: an isolated database, dated sporting records and an illustrative league, with web mutations disabled. See [local setup](setup.md).
