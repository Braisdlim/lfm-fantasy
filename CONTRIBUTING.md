# Contributing and reading the code

Start with [the architecture](docs/architecture.md) and [model contract](docs/criterio.md). Changes should be small enough to explain with a concrete behaviour and relevant evidence.

Create a focused branch and a pull request explaining the problem, resulting behaviour and checks. The [review guide](docs/review.md) provides implementation/test pairs to start with; [decision notes](docs/decisions.md) explain constraints worth preserving. Match the English documentation style when extending public guides; retain domain labels used by the Spanish UI.

- Python: 3.12+, `uv`, Ruff formatting/lint, pytest. Use SQLAlchemy Core and parameterised SQL.
- Web: TypeScript, Svelte 5, server-only secrets. The backend owns recommendation decisions; the UI explains them.
- Collectors: capture source evidence before normalising, respect request pacing and 429/backoff. Automated jobs never execute game purchases, sales or lineup changes.
- Missing data is not zero. Keep source/date scope and uncertainty visible.
- Append schema changes; test them with disposable PostgreSQL. Never run integration tests on production.
- Predictive changes require forward evaluation against simple baselines. Demo results do not prove predictive quality.
- Do not commit `.env`, tokens, real private fixtures, database archives or private screenshots.

Run the README checks and `npm run demo:smoke` for demo/UI changes. CI exercises Python/SQL, web build/types, the trigger logic and the local demo. Public collection is deliberately disabled. Review the exact fields and source rights before replacing the real sporting snapshot; retain dates and do not export private league tables.

Issue reports should include reproduction steps and expected/observed behaviour with a synthetic example. Remove credentials, league identifiers and personal data from logs before attaching them.
