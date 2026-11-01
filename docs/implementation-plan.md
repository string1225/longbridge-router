# Implementation plan

**Goal:** Deploy the OAuth and market-data gateway on 139 and provide a reusable consumer skill.

**Stack:** Python 3.11+, FastAPI, httpx, cryptography, SQLite, systemd, Nginx, HTML/CSS/JavaScript.

- [x] Write and run failing tests for authentication, token lifecycle, routing, OAuth and persistence.
- [x] Implement focused modules: config, store, security, upstream, OAuth, API and static management UI.
- [x] Verify tests, lint and browser management workflows at desktop and mobile widths.
- [x] Document the verified official endpoint mapping and publish OpenAPI plus a consumer skill with a working client helper.
- [x] Deploy locked dependencies, isolated service, HTTPS path and precise Mihomo rules; verify both real egress paths.
- [x] Register OAuth client, verify public management and consumer boundaries and restart persistence.
- [x] Install the consumer skill locally and on 139 and validate it.
- [x] Prepare verified intended artifacts for commit and push under the development rules.

Use inline execution. User delegated implementation and server deployment with “你看着搞一下”; continue through reversible implementation and deployment, leaving actual account consent to the owner.
