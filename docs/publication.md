# Public edition and data provenance

This is a curated snapshot of a private personal application. A fresh Git repository was used so historical private notes and files do not become public through old commits. The operational repository, its Actions secrets and live app remain separate.

Included: application source, schema, tests, lockfiles, local Compose demo and documentation. Excluded: production dumps/raw captures, authentication files, private league runbooks, provider project IDs, production service URLs, backups, local agent tooling and third-party skill bundles.

The demo uses a bounded real public sports snapshot plus an example fantasy league. The snapshot has only ten allowlisted sports tables: players, clubs, prices, weekly points, availability, fixtures, official week timing, player/team set pieces and season stats. It does not include private league tables, raw responses, users, authentication tokens, private recommendations, bids or notes.

Captured on **13 October 2026**: 64 selected players, 20 clubs, 5,107 daily prices, 486 point records, 64 availability records and 130 fixtures. Selection combines high points and high points/value players by position. Missing observations remain missing; original sport dates and source timestamps are preserved. JSON metadata records selection and provenance. The snapshot is at `src/lfm/demo_data.json`.

Sources: [LaLiga Fantasy](https://www.laligafantasy.com/) for official catalogue/prices/points/calendar, and [FútbolFantasy](https://www.futbolfantasy.com/) for availability and auxiliary statistics. Photos/badges reference public upstream URLs; full website pages and asset image binaries are not redistributed by the demo. This is a historical sample, not an automatically updated feed or a grant of source data rights.

Managers, balances, example ownership, auction history, clauses, asking prices and trades are generated. Their role is to exercise the actual algorithms with real sporting inputs. They are not evidence of real transactions or the predictive performance of the private app.

Contract fixtures separately preserve reduced adapter structures and public sporting fields; person names/asset URLs are anonymised and private account, fantasy-team and league IDs are remapped. HTML fixtures are reduced anonymised parser snippets, not full source websites.

The original automatic fixture tool anonymises names and URLs, **not every ID**. Do not publish newly collected fixtures without reviewing all fields and remapping private IDs as this edition did. Never commit raw responses or authentication state.

## Rights

This project is publicly viewable as a personal portfolio. No broad open-source redistribution licence has been selected. The author retains the rights to original code; dependencies retain their own licences. Public visibility alone is not a grant of rights to third-party sports data, logos or brands. Obtain appropriate permission before reusing protected content or operating a redistributed data service.

## Release review

Before publishing changes, run tests, the demo smoke script and a secret scan, inspect new datasets, fixtures and screenshots, and review the staged files. Automated secret scanners reduce risk; they are not proof that arbitrary personal information is absent.
