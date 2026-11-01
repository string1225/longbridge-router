# Longbridge Router on 139

2026-11-01. Deliver one persistent gateway at https://home.sunny-string.cn/longbridge/.

## Architecture

FastAPI serves a compact Chinese management page and versioned JSON API. SQLite WAL stores encrypted OAuth client/token/state records, hashed application tokens and administrator sessions, and bounded audit history. Fernet key and initial administrator password hash live outside Git in a root-readable environment file. Run one uvicorn worker under systemd; serialize refresh and rate limiting in that process.

Prefer explicit market routing over a single global SDK connection, which cannot ensure independent A-share routing. A generic unrestricted reverse proxy would expose account operations and allow accidental trading, so expose an exact read-only endpoint catalog instead.

CN (.SH/.SZ/.BJ) uses openapi.longbridge.cn without an HTTP proxy. HK/US use openapi.longbridge.com via 127.0.0.1:7890. Explicit Mihomo DOMAIN-SUFFIX rules enforce DIRECT for longbridge.cn and PROXY for longbridge.com even with TUN enabled. No fallback across routes. Split mixed quote requests before sending upstream, preserving requested order and decimal strings.

## OAuth

Use dynamic registration, authorization code + PKCE S256, single-use state bound to the administrator session, and a fixed public HTTPS callback. Discover and validate endpoints against the configured issuer. Follow the SDK's default of omitting an explicit scope; allow a configured scope after validating against live discovery. The live service's scopes differ from the documentation's example `3`.

Encrypt access tokens, refresh tokens, client data, and PKCE verifier at rest. Automatically refresh before expiration under a lock, persist rotating refresh tokens atomically, retain the old refresh token if omitted, and flag invalid_grant for administrator reauthorization. Never log callback queries or return upstream tokens. Browser authorization is a user action.

## Administration and consumer access

Secure HttpOnly SameSite=Lax cookies, CSRF token for every management mutation, fixed-origin checks, expiring hashed sessions, scrypt password hashing, login throttling, password changes, and logout. UI: service and OAuth status, connectivity probes, authorize/refresh/disconnect, pause/resume consumer requests, application-token create/rotate/revoke, per-market restrictions, scopes, expiry and quotas, request history, and API/skill downloads. Tokens display only on creation or rotation, are stored as SHA-256 hashes, and never travel in query strings. Default scope is quote:read; account:read is optional. Trading writes are unavailable.

Audit metadata excludes headers, query parameters, request bodies, response data, and secrets. Status distinguishes transport reachability from authorized market access. Consumer APIs, OpenAPI contract, and distributed skill describe errors and real verification limits. Existing account quote entitlements remain decisive.

## Delivery and validation

Test authorization boundaries, routing, OAuth state/PKCE/refresh rotation and concurrency, secret persistence, allowlist protection, quotas and error mapping with mocked upstream responses. Verify current unauthenticated quote endpoints and discovery live on both routes. Test the management workflow at desktop and mobile sizes with Playwright because Browser is unavailable. Deploy an independent loopback service and an isolated Nginx location, validate configuration before reload, verify public HTTPS, restart persistence and protected access. Account data verification requires the owner's browser consent and must be reported separately.
