# Optional scheduling Worker

The Cloudflare Worker dispatches private GitHub Actions jobs according to useful collection windows. `src/schedule.js` contains timezone/DST selection; `src/index.js` handles dispatch, `/health` and authorised manual triggers.

This is an example, not deployed by the public demo. Change the placeholder `REPO` in `wrangler.toml`, review the league-specific schedule, and keep `GITHUB_TOKEN` and `TRIGGER_KEY` in the Worker secret store. Restrict the GitHub token to dispatching Actions in the operational private repository.

```bash
npm test
```

These tests exercise date-window logic without Cloudflare or account credentials. Cron delivery is an attempt, not a guarantee; the backend's recent-run guard prevents duplicate collection. See [deployment](../docs/deployment.md).
