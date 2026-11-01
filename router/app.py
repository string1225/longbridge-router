import asyncio
import contextlib
import hmac
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from router.config import Settings
from router.oauth import OAuth
from router.security import WindowLimiter, digest, hash_password, verify_password
from router.store import Store
from router.upstream import (
    ACCOUNT_PATHS,
    GET_PATHS,
    QUOTE_PATHS,
    Upstream,
    required_scope,
    symbol_market,
    validate_market_payload,
)

STATIC = Path(__file__).parent / "static"
SKILL = Path(__file__).parent.parent / "skills" / "longbridge-router"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(StrictModel):
    password: str = Field(max_length=512)


class PasswordChange(StrictModel):
    current_password: str = Field(max_length=512)
    new_password: str = Field(min_length=14, max_length=512)


class TokenSpec(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    markets: list[Literal["CN", "HK", "US"]] = Field(min_length=1, max_length=3)
    scopes: list[Literal["quote:read", "account:read"]] = Field(min_length=1, max_length=2)
    rate_limit: int = Field(default=60, ge=1, le=600)
    expires_days: int = Field(default=90, ge=1, le=365)


class OAuthStart(StrictModel):
    region: Literal["global", "CN"] = "global"


class Control(StrictModel):
    paused: bool


class RelayRequest(StrictModel):
    method: Literal["GET", "POST"]
    path: str = Field(max_length=160)
    params: dict = Field(default_factory=dict)
    body: dict = Field(default_factory=dict)


class QuoteData(BaseModel):
    securities: list[dict[str, Any]]


class QuoteMeta(BaseModel):
    routes: dict[str, Literal["direct", "proxy"]]
    missing_symbols: list[str]
    request_id: str


class QuoteResponse(BaseModel):
    code: Literal[0] = 0
    data: QuoteData
    meta: QuoteMeta


class RelayMeta(BaseModel):
    market: Literal["CN", "HK", "US"]
    route: Literal["direct", "proxy"]
    request_id: str


class RelayResponse(BaseModel):
    code: Literal[0] = 0
    data: Any
    meta: RelayMeta


def create_app(settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
    store = Store(settings.data_dir, settings.encryption_key)
    upstream = Upstream(settings, transport)
    oauth = OAuth(store, upstream, settings)
    limiter = WindowLimiter()

    async def maintain():
        while True:
            await asyncio.sleep(settings.refresh_interval)
            token = store.secret_get("oauth_tokens")
            if token and not token.get("needs_authorization"):
                try:
                    await oauth.access_token()
                except HTTPException as exc:
                    store.audit("system", "oauth.refresh_failed", status=exc.status_code)
            store.execute("DELETE FROM sessions WHERE expires_at<?", (time.time(),))

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(maintain())
        yield
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await upstream.close()

    app = FastAPI(
        title="Longbridge Router",
        version="0.1.0",
        description="139 长桥行情中转。应用使用 Bearer token；管理接口使用 Cookie 和 CSRF。",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.store, app.state.oauth, app.state.upstream = store, oauth, upstream
    app.state.settings = settings
    app.mount("/assets", StaticFiles(directory=STATIC), name="assets")

    @app.middleware("http")
    async def request_metadata(request, call_next):
        request.state.request_id = secrets.token_hex(12)
        try:
            content_length = int(request.headers.get("content-length", "0") or "0")
        except ValueError:
            return JSONResponse({"error": {"code": "invalid_content_length"}}, status_code=400)
        if content_length > 262144:
            return JSONResponse({"error": {"code": "body_too_large"}}, status_code=413)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        details = exc.detail if isinstance(exc.detail, dict) else {"code": str(exc.detail)}
        if "error" in details:
            details = {
                "code": details["error"],
                **{k: v for k, v in details.items() if k != "error"},
            }
        return JSONResponse(
            {"error": details, "request_id": request.state.request_id},
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        return JSONResponse(
            {
                "error": {
                    "code": "invalid_request",
                    "fields": [
                        {"loc": e["loc"], "type": e["type"], "msg": e["msg"]} for e in exc.errors()
                    ],
                },
                "request_id": request.state.request_id,
            },
            status_code=422,
        )

    def check_origin(request):
        origin = request.headers.get("origin")
        if origin and origin != settings.origin:
            raise HTTPException(403, "origin_not_allowed")

    def session(request):
        session_hash = digest(request.cookies.get("lbr_session", ""))
        rows = store.rows(
            "SELECT * FROM sessions WHERE hash=? AND expires_at>?", (session_hash, time.time())
        )
        if not rows:
            raise HTTPException(401, "admin_login_required")
        return rows[0]

    async def admin_required(request: Request):
        current = session(request)
        if request.method not in {"GET", "HEAD"}:
            check_origin(request)
            if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), current["csrf"]):
                raise HTTPException(403, "csrf_invalid")
        request.state.session = current
        return current

    bearer = HTTPBearer(auto_error=False)

    async def consumer(
        request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)
    ):
        token = store.authenticate(credentials.credentials) if credentials else None
        if not token:
            raise HTTPException(
                401, "application_token_invalid", headers={"WWW-Authenticate": "Bearer"}
            )
        limiter.check("token:" + token["id"], token["rate_limit"])
        request.state.consumer = token
        return token

    admin = APIRouter(prefix="/admin", dependencies=[Depends(admin_required)], tags=["Management"])

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(STATIC / "index.html", media_type="text/html")

    @app.get("/healthz", tags=["Health"])
    async def health():
        store.rows("SELECT 1")
        return {"status": "ok", "version": "0.1.0"}

    @app.post("/admin/login", tags=["Management"])
    async def login(body: Login, request: Request):
        check_origin(request)
        limiter.check("login:" + request.client.host, 10, 600)
        stored_hash = store.secret_get("admin_password_hash", settings.admin_password_hash)
        if not verify_password(body.password, stored_hash):
            store.audit("anonymous", "admin.login_failed", status=401)
            raise HTTPException(401, "invalid_password")
        raw, csrf = secrets.token_urlsafe(40), secrets.token_urlsafe(32)
        store.execute("DELETE FROM sessions WHERE expires_at<?", (time.time(),))
        store.execute(
            "INSERT INTO sessions VALUES (?,?,?)", (digest(raw), csrf, time.time() + 43200)
        )
        response = JSONResponse({"csrf_token": csrf})
        response.set_cookie(
            "lbr_session",
            raw,
            max_age=43200,
            httponly=True,
            secure=settings.public_url.startswith("https:"),
            samesite="lax",
            path=(settings.root_path or "") + "/",
        )
        store.audit("admin", "admin.login")
        return response

    @admin.get("/session")
    async def get_session(request: Request):
        return {"csrf_token": request.state.session["csrf"]}

    @admin.post("/logout")
    async def logout(request: Request):
        store.execute("DELETE FROM sessions WHERE hash=?", (request.state.session["hash"],))
        response = JSONResponse({"ok": True})
        response.delete_cookie("lbr_session", path=(settings.root_path or "") + "/")
        return response

    @admin.post("/password")
    async def password_change(body: PasswordChange):
        if not verify_password(
            body.current_password,
            store.secret_get("admin_password_hash", settings.admin_password_hash),
        ):
            raise HTTPException(401, "invalid_password")
        store.secret_set("admin_password_hash", hash_password(body.new_password))
        store.execute("DELETE FROM sessions")
        store.execute("DELETE FROM states")
        store.audit("admin", "admin.password_changed")
        return {"ok": True}

    @admin.get("/status")
    async def status():
        tokens = store.tokens()
        counts = store.rows(
            """SELECT count(*) AS requests,
            coalesce(sum(CASE WHEN status>=400 THEN 1 ELSE 0 END),0) AS failures
            FROM events WHERE created_at>? AND actor!='admin' AND actor!='system'""",
            (time.time() - 86400,),
        )[0]
        return {
            "service": "Longbridge Router",
            "version": "0.1.0",
            "server_time": time.time(),
            "paused": store.secret_get("paused", False),
            "oauth": oauth.status(),
            "routes": {
                "CN": {"upstream": "openapi.longbridge.cn", "egress": "direct"},
                "HK": {"upstream": "openapi.longbridge.com", "egress": "proxy"},
                "US": {"upstream": "openapi.longbridge.com", "egress": "proxy"},
            },
            "active_tokens": sum(
                not t["revoked"] and t["expires_at"] > time.time() for t in tokens
            ),
            "usage_24h": counts,
            "network": store.secret_get("network", {}),
            "public_url": settings.public_url,
            "callback_url": oauth.callback_url,
            "upstream_rps": settings.upstream_rps,
        }

    @admin.post("/control")
    async def control(body: Control):
        store.secret_set("paused", body.paused)
        store.audit("admin", "service.paused" if body.paused else "service.resumed")
        return {"paused": body.paused}

    @admin.post("/network/check")
    async def network_check():
        result = await upstream.connectivity()
        store.secret_set("network", {"checked_at": time.time(), "markets": result})
        store.audit("admin", "network.check")
        return result

    @admin.post("/oauth/start")
    async def oauth_start(body: OAuthStart, request: Request):
        url = await oauth.start(body.region, request.state.session["hash"])
        store.audit("admin", "oauth.start")
        return {"authorization_url": url}

    @app.get("/oauth/callback", include_in_schema=False)
    async def oauth_callback(request: Request, state: str = "", code: str = "", error: str = ""):
        try:
            current = session(request)
        except HTTPException as exc:
            raise HTTPException(400, "oauth_admin_session_required") from exc
        await oauth.callback(state, current["hash"], "" if error else code)
        store.audit("admin", "oauth.authorized")
        return RedirectResponse(settings.public_url.rstrip("/") + "/#authorized", status_code=303)

    @admin.post("/oauth/refresh")
    async def oauth_refresh():
        await oauth.access_token(force=True)
        store.audit("admin", "oauth.refresh")
        return oauth.status()

    @admin.delete("/oauth")
    async def oauth_disconnect():
        await oauth.disconnect()
        store.audit("admin", "oauth.disconnected")
        return {"ok": True}

    @admin.get("/tokens")
    async def tokens():
        return {"tokens": store.tokens()}

    @admin.post("/tokens", status_code=201)
    async def token_create(body: TokenSpec):
        spec = body.model_dump(exclude={"expires_days"})
        spec["expires_at"] = time.time() + body.expires_days * 86400
        result = store.create_token(spec)
        store.audit("admin", "token.created")
        return result

    @admin.post("/tokens/{token_id}/rotate")
    async def token_rotate(token_id: str):
        previous = next((t for t in store.tokens() if t["id"] == token_id), None)
        if not previous or previous["revoked"] or previous["expires_at"] <= time.time():
            raise HTTPException(404, "active_token_not_found")
        result = store.create_token(previous, revoke=token_id)
        store.audit("admin", "token.rotated")
        return result

    @admin.delete("/tokens/{token_id}")
    async def token_revoke(token_id: str):
        if not store.execute("UPDATE tokens SET revoked=1 WHERE id=?", (token_id,)):
            raise HTTPException(404, "token_not_found")
        store.audit("admin", "token.revoked")
        return {"ok": True}

    @admin.get("/events")
    async def events(limit: int = Query(60, ge=1, le=200)):
        return {"events": store.rows("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))}

    @admin.get("/skill")
    async def skill_download():
        return FileResponse(SKILL / "SKILL.md", media_type="text/markdown", filename="SKILL.md")

    @admin.get("/skill-bundle")
    async def skill_bundle():
        import io
        import zipfile

        from fastapi.responses import Response

        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as bundle:
            for path in SKILL.rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts:
                    bundle.write(path, "longbridge-router/" + path.relative_to(SKILL).as_posix())
        return Response(
            stream.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="longbridge-router-skill.zip"'},
        )

    app.include_router(admin)
    api = APIRouter(prefix="/v1", tags=["Consumer"])

    def allowed(token, market, scope="quote:read"):
        if market not in token["markets"] or scope not in token["scopes"]:
            raise HTTPException(403, "token_permission_denied")

    async def relay(request, token, market, method, path, params=None, body=None):
        scope = required_scope(method, path)
        allowed(token, market, scope)
        validate_market_payload(params or {}, market)
        validate_market_payload(body or {}, market)
        if (path.endswith("/hk") and market != "HK") or (path.endswith("/us") and market != "US"):
            raise HTTPException(422, "path_market_mismatch")
        if store.secret_get("paused", False):
            raise HTTPException(503, "service_paused")
        start, result_status = time.monotonic(), 200
        try:
            access_token = await oauth.access_token()
            client = store.secret_get("oauth_client")
            return await upstream.data(
                market, method, path, access_token, params, body, client_id=client["client_id"]
            )
        except HTTPException as exc:
            result_status = exc.status_code
            raise
        finally:
            store.audit(
                token["id"],
                method + " " + path,
                market,
                result_status,
                round((time.monotonic() - start) * 1000),
                request.state.request_id,
            )

    @api.get("/status")
    async def api_status(token=Depends(consumer)):
        return {
            "code": 0,
            "data": {
                "paused": store.secret_get("paused", False),
                "oauth": oauth.status(),
                "markets": token["markets"],
                "scopes": token["scopes"],
            },
        }

    @api.get("/catalog")
    async def catalog(token=Depends(consumer)):
        return {
            "code": 0,
            "data": {
                "operations": [
                    {"method": method, "path": path, "scope": scope}
                    for method, paths, scope in [
                        ("POST", QUOTE_PATHS, "quote:read"),
                        ("GET", GET_PATHS, "quote:read"),
                        ("GET", ACCOUNT_PATHS, "account:read"),
                    ]
                    if scope in token["scopes"]
                    for path in sorted(paths)
                ],
                "markets": token["markets"],
            },
        }

    @api.get("/quotes", response_model=QuoteResponse)
    async def quotes(
        request: Request,
        symbols: str = Query(min_length=1, max_length=12000),
        token=Depends(consumer),
    ):
        requested = [s.strip().upper() for s in symbols.split(",")]
        if len(requested) > 500:
            raise HTTPException(422, "maximum_500_symbols")
        grouped = {}
        for symbol in requested:
            market = symbol_market(symbol)
            allowed(token, market)
            grouped.setdefault(market, [])
            if symbol not in grouped[market]:
                grouped[market].append(symbol)
        results = await asyncio.gather(
            *(
                relay(request, token, m, "POST", "/quote/quotes", body={"symbol": group})
                for m, group in grouped.items()
            ),
            return_exceptions=True,
        )
        # Finish all in-flight reads before returning a failure.
        for result in results:
            if isinstance(result, BaseException):
                raise result
        securities = {}
        for result in results:
            data = result.get("data", result)
            items = None
            if isinstance(data, dict):
                items = []
                for key in ("secu_quote", "secuQuote", "securities"):
                    if key in data:
                        items = data[key] if data[key] is not None else []
                        break
            if not isinstance(items, list):
                raise HTTPException(502, "upstream_quote_schema_mismatch")
            for item in items:
                securities[item["symbol"]] = item
        return {
            "code": 0,
            "data": {"securities": [securities[s] for s in requested if s in securities]},
            "meta": {
                "routes": {m: "direct" if m == "CN" else "proxy" for m in grouped},
                "missing_symbols": [s for s in requested if s not in securities],
                "request_id": request.state.request_id,
            },
        }

    @api.post("/markets/{market}/request", response_model=RelayResponse)
    async def api_request(
        request: Request,
        market: Literal["CN", "HK", "US"],
        body: RelayRequest,
        token=Depends(consumer),
    ):
        result = await relay(request, token, market, body.method, body.path, body.params, body.body)
        return {
            "code": 0,
            "data": result.get("data", result),
            "meta": {
                "market": market,
                "route": "direct" if market == "CN" else "proxy",
                "request_id": request.state.request_id,
            },
        }

    app.include_router(api)
    return app
