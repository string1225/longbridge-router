import asyncio
import base64
import hashlib
import math
import secrets
import time
from urllib.parse import urlencode

from fastapi import HTTPException

from router.upstream import BASES


class OAuth:
    def __init__(self, store, upstream, settings):
        self.store, self.upstream, self.settings = store, upstream, settings
        self.lock = asyncio.Lock()

    def status(self):
        client = self.store.secret_get("oauth_client", {})
        token = self.store.secret_get("oauth_tokens", {})
        return {
            "client_registered": bool(client.get("client_id")),
            "region": client.get("region", "global"),
            "authorized": bool(token.get("access_token"))
            and not token.get("needs_authorization", False),
            "expires_at": token.get("expires_at"),
            "last_refresh_at": token.get("last_refresh_at"),
            "needs_authorization": not bool(token) or token.get("needs_authorization", False),
            "last_error": token.get("last_error"),
        }

    async def discovery(self, region):
        response = await self.upstream.request(
            region, "GET", "/.well-known/oauth-authorization-server"
        )
        try:
            data = response.json()
        except ValueError as exc:
            raise HTTPException(502, "oauth_discovery_failed") from exc
        base = BASES["CN" if region == "CN" else "global"]
        expected = {
            "issuer": base,
            "authorization_endpoint": base + "/oauth2/authorize",
            "token_endpoint": base + "/oauth2/token",
            "registration_endpoint": base + "/oauth2/register",
        }
        if not response.is_success or any(data.get(k) != v for k, v in expected.items()):
            raise HTTPException(502, "oauth_discovery_endpoint_mismatch")
        if self.settings.oauth_scope and not set(self.settings.oauth_scope.split()).issubset(
            data.get("scopes_supported", [])
        ):
            raise HTTPException(409, "configured_oauth_scope_not_supported")
        return data

    async def register(self, region):
        await self.discovery(region)
        response = await self.upstream.request(
            region,
            "POST",
            "/oauth2/register",
            json={
                "client_name": "Longbridge Router 139",
                "redirect_uris": [self.callback_url],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
        )
        try:
            data = response.json()
        except ValueError as exc:
            raise HTTPException(502, "oauth_registration_failed") from exc
        if not response.is_success or not data.get("client_id"):
            raise HTTPException(502, "oauth_registration_failed")
        client = {"client_id": data["client_id"], "region": region}
        if data.get("client_secret"):
            client["client_secret"] = data["client_secret"]
        self.store.secret_set("oauth_client", client)
        return client

    @property
    def callback_url(self):
        return self.settings.public_url.rstrip("/") + "/oauth/callback"

    async def start(self, region, session_hash):
        async with self.lock:
            client = self.store.secret_get("oauth_client")
            if client and client["region"] != region:
                raise HTTPException(409, "disconnect_before_changing_oauth_region")
            if not client:
                client = await self.register(region)
            discovery = await self.discovery(region)
            state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
            challenge = (
                base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                .rstrip(b"=")
                .decode()
            )
            self.store.state_create(state, session_hash, {"verifier": verifier, "client": client})
            query = {
                "response_type": "code",
                "client_id": client["client_id"],
                "redirect_uri": self.callback_url,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
            if self.settings.oauth_scope:
                query["scope"] = self.settings.oauth_scope
            return discovery["authorization_endpoint"] + "?" + urlencode(query)

    async def exchange(self, client, form, previous=None):
        form["client_id"] = client["client_id"]
        if client.get("client_secret"):
            form["client_secret"] = client["client_secret"]
        response = await self.upstream.request(client["region"], "POST", "/oauth2/token", data=form)
        try:
            data = response.json()
        except ValueError as exc:
            raise HTTPException(502, "oauth_invalid_token_response") from exc
        if data.get("error") == "invalid_grant":
            if previous:
                self.store.secret_set(
                    "oauth_tokens",
                    {**previous, "needs_authorization": True, "last_error": "invalid_grant"},
                )
            raise HTTPException(409, "oauth_reauthorization_required")
        if not response.is_success or not data.get("access_token"):
            raise HTTPException(502, "oauth_token_exchange_failed")
        try:
            expires_in = float(data["expires_in"])
            if not math.isfinite(expires_in) or expires_in <= 0:
                raise ValueError()
        except (ValueError, TypeError, KeyError) as exc:
            raise HTTPException(502, "oauth_invalid_expiration") from exc
        token = {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token") or (previous or {}).get("refresh_token"),
            "expires_at": time.time() + expires_in,
            "last_refresh_at": time.time(),
            "needs_authorization": False,
        }
        self.store.secret_set("oauth_tokens", token)
        return token

    async def callback(self, state, session_hash, code):
        async with self.lock:
            pending = self.store.state_consume(state, session_hash)
            if not pending:
                raise HTTPException(400, "oauth_state_invalid_or_expired")
            if not code:
                raise HTTPException(400, "oauth_authorization_declined")
            await self.exchange(
                pending["client"],
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.callback_url,
                    "code_verifier": pending["verifier"],
                },
            )

    async def access_token(self, force=False):
        async with self.lock:
            token = self.store.secret_get("oauth_tokens")
            client = self.store.secret_get("oauth_client")
            if not token or not client or token.get("needs_authorization"):
                raise HTTPException(409, "oauth_authorization_required")
            if force or token["expires_at"] < time.time() + 120:
                if not token.get("refresh_token"):
                    raise HTTPException(409, "oauth_refresh_token_missing")
                token = await self.exchange(
                    client,
                    {"grant_type": "refresh_token", "refresh_token": token["refresh_token"]},
                    previous=token,
                )
            return token["access_token"]

    async def disconnect(self):
        async with self.lock:
            self.store.secret_delete("oauth_tokens")
            self.store.secret_delete("oauth_client")
            self.store.execute("DELETE FROM states")
