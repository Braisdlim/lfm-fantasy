# Security

Do not include credentials or private database dumps in a public issue. Use GitHub private vulnerability reporting if enabled, or contact the repository owner privately. If a token is exposed, revoke/rotate it before discussing the incident.

This application currently protects a single private workspace with one password; it is not a hardened multi-tenant identity system. The production hook refuses an unset password. Keep live deployments private, use HTTPS, strong credentials, restricted database roles and a provider secret store.

Demo mode requires the dedicated `lfm_demo` database/role and rejects write HTTP methods. Its Compose ports bind to loopback. Do not repurpose the public demo as a production database deployment.

The game client stores rotating authentication tokens locally or in its private database. Backups exclude that token table but can still contain private league data. Protect logs, raw captures and archives. Short web caches are process-local and currently assume a single owner; audit tenant scoping before sharing infrastructure between owners.
