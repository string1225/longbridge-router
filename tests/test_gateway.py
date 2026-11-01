import asyncio
import hashlib
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from router.app import create_app
from router.config import Settings
from router.security import hash_password


@pytest.fixture
def gateway(tmp_path):
    seen = []
    token_responses = []
    overrides = {}

    def upstream(request):
        body = (
            json.loads(request.content)
            if request.content
            and request.headers.get("content-type", "").startswith("application/json")
            else request.content.decode()
        )
        seen.append((request, body))
        if request.url.path in overrides:
            return httpx.Response(200, json=overrides[request.url.path])
        host = str(request.url).split("/")[2]
        base = "https://" + host
        if request.url.path == "/.well-known/oauth-authorization-server":
            return httpx.Response(
                200,
                json={
                    "issuer": base,
                    "authorization_endpoint": base + "/oauth2/authorize",
                    "token_endpoint": base + "/oauth2/token",
                    "registration_endpoint": base + "/oauth2/register",
                    "scopes_supported": ["4", "6", "10", "11"],
                },
            )
        if request.url.path == "/oauth2/register":
            return httpx.Response(201, json={"client_id": "client-test"})
        if request.url.path == "/oauth2/token":
            result = (
                token_responses.pop(0)
                if token_responses
                else {
                    "access_token": "new-access",
                    "refresh_token": "rotated-refresh",
                    "expires_in": 3600,
                }
            )
            return httpx.Response(400 if "error" in result else 200, json=result)
        if request.url.path == "/quote/quotes":
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "secu_quote": [
                            {"symbol": s, "last_done": "123.450"} for s in body["symbol"]
                        ]
                    },
                },
            )
        return httpx.Response(200, json={"code": 0, "data": {"ok": True}})

    settings = Settings(
        data_dir=tmp_path,
        public_url="https://testserver",
        encryption_key=Fernet.generate_key().decode(),
        admin_password_hash=hash_password("test-password-is-long"),
        upstream_rps=1000,
    )
    app = create_app(settings, transport=httpx.MockTransport(upstream))
    app.state.test_upstream_responses = overrides
    with TestClient(app, base_url="https://testserver") as client:
        assert (
            client.post("/admin/login", json={"password": "test-password-is-long"}).status_code
            == 200
        )
        csrf = client.get("/admin/session").json()["csrf_token"]
        client.headers["x-csrf-token"] = csrf
        yield client, app, seen, token_responses


def issue(client, **changes):
    body = {
        "name": "test agent",
        "markets": ["CN", "HK", "US"],
        "scopes": ["quote:read"],
        "rate_limit": 60,
        "expires_days": 30,
        **changes,
    }
    response = client.post("/admin/tokens", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def authorize(app, expired=False):
    app.state.store.secret_set("oauth_client", {"client_id": "client-test", "region": "global"})
    app.state.store.secret_set(
        "oauth_tokens",
        {
            "access_token": "access-secret",
            "refresh_token": "refresh-secret",
            "expires_at": time.time() + (-10 if expired else 3600),
        },
    )


def test_auth_and_csrf(gateway):
    client, app, *_ = gateway
    assert client.get("/healthz").status_code == 200
    assert client.get("/v1/status").status_code == 401
    assert client.post("/admin/tokens", json={}, headers={"x-csrf-token": "bad"}).status_code == 403
    assert (
        client.post(
            "/admin/control", json={"paused": True}, headers={"origin": "https://evil.test"}
        ).status_code
        == 403
    )
    client.cookies.clear()
    assert client.get("/admin/status").status_code == 401
    assert client.post("/admin/login", json={"password": "bad"}).status_code == 401


def test_token_scope_market_revoke_and_hash(gateway):
    client, app, seen, _ = gateway
    token = issue(client, markets=["CN"])
    raw = token["token"]
    headers = {"authorization": "Bearer " + raw}
    assert client.get("/v1/status", headers=headers).status_code == 200
    assert client.get("/v1/quotes?symbols=AAPL.US", headers=headers).status_code == 403
    denied = client.post(
        "/v1/markets/CN/request",
        headers=headers,
        json={
            "method": "GET",
            "path": "/v1/asset/account",
        },
    )
    assert denied.status_code == 403
    listing = client.get("/admin/tokens").text
    assert raw not in listing
    assert raw.encode() not in app.state.store.path.read_bytes()
    assert client.delete("/admin/tokens/" + token["id"]).status_code == 200
    assert client.get("/v1/status", headers=headers).status_code == 401


def test_rotate_expiry_and_rate_limit(gateway):
    client, app, *_ = gateway
    token = issue(client, rate_limit=2)
    headers = {"authorization": "Bearer " + token["token"]}
    assert client.get("/v1/status", headers=headers).status_code == 200
    assert client.get("/v1/status", headers=headers).status_code == 200
    limited = client.get("/v1/status", headers=headers)
    assert limited.status_code == 429 and limited.headers["retry-after"]
    rotated = client.post("/admin/tokens/" + token["id"] + "/rotate").json()
    assert client.get("/v1/status", headers=headers).status_code == 401
    assert (
        client.get(
            "/v1/status", headers={"authorization": "Bearer " + rotated["token"]}
        ).status_code
        == 200
    )
    app.state.store.execute("UPDATE tokens SET expires_at=0 WHERE id=?", (rotated["id"],))
    assert (
        client.get(
            "/v1/status", headers={"authorization": "Bearer " + rotated["token"]}
        ).status_code
        == 401
    )


def test_mixed_quotes_split_routes_and_keep_decimals(gateway):
    client, app, seen, _ = gateway
    authorize(app)
    token = issue(client)
    response = client.get(
        "/v1/quotes?symbols=AAPL.US,600519.SH,700.HK,000001.SZ",
        headers={"authorization": "Bearer " + token["token"]},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert [x["symbol"] for x in result["data"]["securities"]] == [
        "AAPL.US",
        "600519.SH",
        "700.HK",
        "000001.SZ",
    ]
    assert result["data"]["securities"][0]["last_done"] == "123.450"
    quotes = [(r, b) for r, b in seen if r.url.path == "/quote/quotes"]
    assert len(quotes) == 3
    assert (
        next(r for r, b in quotes if "600519.SH" in b["symbol"]).url.host == "openapi.longbridge.cn"
    )
    assert (
        next(r for r, b in quotes if "AAPL.US" in b["symbol"]).url.host == "openapi.longbridge.com"
    )
    assert result["meta"]["routes"]["CN"] == "direct"
    status = client.get("/admin/status").text
    assert "access-secret" not in status and "refresh-secret" not in status


@pytest.mark.parametrize(
    "path",
    [
        "https://evil.test/",
        "//evil.test",
        "/oauth2/token",
        "/quote/../oauth2/token",
        "/quote/quotes?x=y",
        "/v1/trade/order",
        "/quote/quotes/",
    ],
)
def test_proxy_allowlist_prevents_ssrf_and_writes(gateway, path):
    client, app, seen, _ = gateway
    authorize(app)
    token = issue(client, scopes=["quote:read", "account:read"])
    response = client.post(
        "/v1/markets/US/request",
        json={"method": "POST", "path": path},
        headers={"authorization": "Bearer " + token["token"]},
    )
    assert response.status_code == 403
    assert not seen


def test_market_mismatch_and_pause(gateway):
    client, app, seen, _ = gateway
    authorize(app)
    token = issue(client)
    headers = {"authorization": "Bearer " + token["token"]}
    for payload in [
        {"symbol": ["AAPL.US"]},
        {"nested": {"symbols": ["AAPL.US"]}},
        {"market": "US"},
    ]:
        response = client.post(
            "/v1/markets/CN/request",
            headers=headers,
            json={
                "method": "POST",
                "path": "/quote/quotes",
                "body": payload,
            },
        )
        assert response.status_code == 422
    assert client.post("/admin/control", json={"paused": True}).status_code == 200
    assert client.get("/v1/quotes?symbols=700.HK", headers=headers).status_code == 503
    assert client.get("/v1/status", headers=headers).json()["data"]["paused"] is True
    assert not seen


def test_oauth_pkce_session_binding_and_state_replay(gateway):
    client, app, seen, _ = gateway
    start = client.post("/admin/oauth/start", json={"region": "global"})
    assert start.status_code == 200, start.text
    query = parse_qs(urlparse(start.json()["authorization_url"]).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == ["https://testserver/oauth/callback"]
    state = query["state"][0]
    cookies = dict(client.cookies)
    client.cookies.clear()
    assert (
        client.get(
            "/oauth/callback", params={"state": state, "code": "test-code"}, follow_redirects=False
        ).status_code
        == 400
    )
    client.cookies.update(cookies)
    good = client.get(
        "/oauth/callback", params={"state": state, "code": "test-code"}, follow_redirects=False
    )
    assert good.status_code == 303
    assert app.state.store.secret_get("oauth_tokens")["access_token"] == "new-access"
    token_body = parse_qs(next(b for r, b in seen if r.url.path == "/oauth2/token"))
    challenge = hashlib.sha256(token_body["code_verifier"][0].encode()).digest()
    import base64

    assert base64.urlsafe_b64encode(challenge).rstrip(b"=").decode() == query["code_challenge"][0]
    assert (
        client.get("/oauth/callback", params={"state": state, "code": "test-code"}).status_code
        == 400
    )
    assert b"rotated-refresh" not in app.state.store.path.read_bytes()


def test_refresh_rotation_and_missing_refresh_token(gateway):
    client, app, seen, responses = gateway
    authorize(app, expired=True)
    assert client.post("/admin/oauth/refresh").status_code == 200
    assert app.state.store.secret_get("oauth_tokens")["refresh_token"] == "rotated-refresh"
    responses.append({"access_token": "next-access", "expires_in": 3600})
    assert client.post("/admin/oauth/refresh").status_code == 200
    assert app.state.store.secret_get("oauth_tokens")["refresh_token"] == "rotated-refresh"
    responses.append({"error": "invalid_grant", "error_description": "refresh-secret"})
    failed = client.post("/admin/oauth/refresh")
    assert failed.status_code == 409 and "refresh-secret" not in failed.text
    assert client.get("/admin/status").json()["oauth"]["needs_authorization"] is True


@pytest.mark.asyncio
async def test_concurrent_refresh_is_single_flight(gateway):
    _, app, seen, _ = gateway
    authorize(app, expired=True)
    await asyncio.gather(*(app.state.oauth.access_token() for _ in range(8)))
    assert len([r for r, b in seen if r.url.path == "/oauth2/token"]) == 1


def test_password_change_invalidates_sessions_and_persists(gateway):
    client, app, *_ = gateway
    response = client.post(
        "/admin/password",
        json={
            "current_password": "test-password-is-long",
            "new_password": "a-new-and-long-password",
        },
    )
    assert response.status_code == 200
    assert client.get("/admin/status").status_code == 401
    assert (
        client.post("/admin/login", json={"password": "test-password-is-long"}).status_code == 401
    )
    assert (
        client.post("/admin/login", json={"password": "a-new-and-long-password"}).status_code == 200
    )


def test_unconfigured_upstream_and_connectivity(gateway):
    client, app, *_ = gateway
    token = issue(client)
    response = client.get(
        "/v1/quotes?symbols=700.HK", headers={"authorization": "Bearer " + token["token"]}
    )
    assert response.status_code == 409
    checks = client.post("/admin/network/check").json()
    assert checks["CN"]["reachable"] is True and checks["US"]["reachable"] is True
    assert client.get("/openapi.json").status_code == 200


@pytest.mark.parametrize("access,dc", [("us_real-token", "us"), ("ap_real-token", "ap")])
def test_oauth_headers_follow_official_sdk_contract(gateway, access, dc):
    client, app, seen, _ = gateway
    authorize(app)
    stored = app.state.store.secret_get("oauth_tokens")
    app.state.store.secret_set("oauth_tokens", {**stored, "access_token": access})
    token = issue(client)
    response = client.get(
        "/v1/quotes?symbols=AAPL.US", headers={"authorization": "Bearer " + token["token"]}
    )
    assert response.status_code == 200
    request = next(r for r, _ in seen if r.url.path == "/quote/quotes")
    assert request.headers["x-dc-region"] == dc
    assert request.headers["authorization"] == "Bearer " + access
    assert request.headers["x-api-key"] == "client-test"
    assert abs(int(request.headers["x-timestamp"]) - time.time()) < 10


@pytest.mark.parametrize("data", [{}, {"secu_quote": None}, {"secuQuote": None}])
def test_empty_proto_quotes_report_missing_symbols(gateway, data):
    client, app, *_ = gateway
    authorize(app)
    app.state.test_upstream_responses["/quote/quotes"] = {"code": 0, "data": data}
    token = issue(client)
    response = client.get(
        "/v1/quotes?symbols=AAPL.US", headers={"authorization": "Bearer " + token["token"]}
    )
    assert response.status_code == 200
    assert response.json()["data"]["securities"] == []
    assert response.json()["meta"]["missing_symbols"] == ["AAPL.US"]
