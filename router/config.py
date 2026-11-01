import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    public_url: str
    encryption_key: str
    admin_password_hash: str
    proxy_url: str = "http://127.0.0.1:7890"
    upstream_rps: float = 8
    oauth_scope: str = ""
    refresh_interval: float = 60

    def __post_init__(self):
        parsed = urlsplit(self.public_url)
        if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1"}:
            raise ValueError("Public URL must use HTTPS")
        if parsed.query or parsed.fragment or parsed.username or not parsed.hostname:
            raise ValueError("Invalid public URL")
        Fernet(self.encryption_key.encode())
        if not self.admin_password_hash or self.upstream_rps <= 0:
            raise ValueError("Admin password hash and positive upstream RPS required")

    @property
    def root_path(self):
        return urlsplit(self.public_url).path.rstrip("/")

    @property
    def origin(self):
        p = urlsplit(self.public_url)
        return f"{p.scheme}://{p.netloc}"

    @classmethod
    def from_env(cls):
        return cls(
            data_dir=Path(os.environ.get("ROUTER_DATA_DIR", "/var/lib/longbridge-router")),
            public_url=os.environ["ROUTER_PUBLIC_URL"].rstrip("/"),
            encryption_key=os.environ["ROUTER_ENCRYPTION_KEY"],
            admin_password_hash=os.environ["ROUTER_ADMIN_PASSWORD_HASH"],
            proxy_url=os.environ.get("ROUTER_PROXY_URL", "http://127.0.0.1:7890"),
            upstream_rps=float(os.environ.get("ROUTER_UPSTREAM_RPS", "8")),
            oauth_scope=os.environ.get("ROUTER_OAUTH_SCOPE", ""),
        )
