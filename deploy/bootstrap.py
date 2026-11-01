"""Initialize private runtime configuration once; never print credentials."""

import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet

from router.security import hash_password

env_path = Path("/etc/longbridge-router.env")
if env_path.exists():
    print("Runtime configuration retained")
else:
    password = secrets.token_urlsafe(24)
    key = Fernet.generate_key().decode()
    with os.fdopen(os.open(env_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w") as out:
        out.write("ROUTER_PUBLIC_URL=https://home.sunny-string.cn/longbridge\n")
        out.write("ROUTER_DATA_DIR=/var/lib/longbridge-router\n")
        out.write("ROUTER_PROXY_URL=http://127.0.0.1:7890\n")
        out.write("ROUTER_ENCRYPTION_KEY=" + key + "\n")
        out.write("ROUTER_ADMIN_PASSWORD_HASH=" + hash_password(password) + "\n")
    handoff = Path("/home/junte/.config/longbridge-router")
    handoff.mkdir(parents=True, exist_ok=True, mode=0o700)
    credential = handoff / "bootstrap.txt"
    credential.write_text(
        "管理地址：https://home.sunny-string.cn/longbridge/\n"
        "管理员初始密码：" + password + "\n"
        "首次登录后可在管理设置中修改密码。此文件包含密码，请私密保存。\n",
        encoding="utf-8",
    )
    credential.chmod(0o600)
    import pwd

    owner = pwd.getpwnam("junte")
    os.chown(handoff, owner.pw_uid, owner.pw_gid)
    os.chown(credential, owner.pw_uid, owner.pw_gid)
    print("Runtime initialized; private bootstrap handoff written")
