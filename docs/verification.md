# Verification — 2026-11-01

## Automated and independent checks

- 22 pytest cases pass on Python 3.14. Routing, consumer scope/market/expiry/revocation/rotation/quotas, CSRF/origin/password boundaries, OAuth PKCE and single-use session-bound state, concurrent refresh and rotating refresh tokens, encrypted persistence, real proto response keys and empty results, and SDK OAuth data-center headers are covered.
- Ruff passes for router, tests, deployment utilities and distributed client. JavaScript syntax checks pass. Skill Creator validator passes for repository and locally installed skill. Editable development installation succeeds.
- Independent review found missing OAuth data-center headers, legal empty proto results and a watchlist path mismatch. All were corrected, with regression coverage for routing headers and empty results. The final request headers match the official SDK's Bearer, client_id, timestamp and DC-region construction.

## Live 139 and browser acceptance

- Python 3.11 service starts under the dedicated system user with root-owned 0644 source, root-only 0600 environment and service-owned 0700 state directory / 0600 SQLite database.
- Public HTTPS management page, JS, CSS, health and OpenAPI load successfully behind the existing Nginx subpath. Nginx configuration passes validation. Service is enabled at boot; no global VPN restart was needed.
- Mihomo live connection snapshots show `longbridge.cn` matched DomainSuffix / DIRECT, and `longbridge.com` matched DomainSuffix / proxy. Discovery returns 200 on each path, and unauthenticated `/quote/quotes` returns 401 on each path, confirming the exact endpoint exists.
- Playwright over installed Edge (Browser plugin unavailable), at 1440×1024 and 390×844: login, real network probes, create/rotate/revoke token, consumer status, revoked-token rejection, unconfigured OAuth 409, pause/resume 503, audit records, Skill ZIP download, OpenAPI, actual dynamic OAuth registration and PKCE URL all pass. No JavaScript runtime exceptions. The distributed Python client successfully calls the live status endpoint.
- Browser inspection covered navigation, text hierarchy, real status badges, table rows, form actions, modal secret clearing, and mobile layout. The market table intentionally scrolls horizontally on narrow displays; page-level content does not overflow. No bitmap concept comparison was available because image generation tools were absent.
- Corrected issues found by browser testing: Uvicorn subpath/static-resource handling, an initial session-check/login input race and synchronous secret clearing on dialog close.
- Restarting systemd preserves the administrator session, registered OAuth client, saved network checks and service control state. All temporary application tokens are revoked; the service is resumed and has zero active tokens.
- Development skill is installed in the local Codex skills directory and `/home/junte/.codex/skills/longbridge-router` on 139; management UI also distributes the bundle.

Screenshots are local QA artifacts under `artifacts/` and excluded from Git. Image contents were inspected directly. Initial administrator password handoff lives outside the repository.

## Requires owner action

The owner must log in to the management page and click “连接长桥账户” to finish browser consent. Real account quotes, account-specific data entitlements, live A-share availability, and end-to-end refresh against that account cannot be certified before consent. Do not interpret successful transport tests or mocked refresh tests as actual account-data acceptance.
