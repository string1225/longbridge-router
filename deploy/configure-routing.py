"""Add two explicit Mihomo rules, validate, then reload without restarting the VPN."""

import datetime
import json
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path

config = Path("/etc/mihomo/config.yaml")
original = config.read_text()
rules = ["- DOMAIN-SUFFIX,longbridge.cn,DIRECT", "- DOMAIN-SUFFIX,longbridge.com,PROXY"]
missing = [rule for rule in rules if rule not in original.splitlines()]
if missing:
    if not re.search(r"^rules:\s*$", original, re.M):
        raise SystemExit("Mihomo rules block not found; configuration unchanged")
    updated = re.sub(r"^rules:\s*$", "rules:\n" + "\n".join(missing), original, count=1, flags=re.M)
    backup = config.with_name(
        "config.yaml.before-longbridge-" + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    )
    shutil.copy2(config, backup)
    backup.chmod(0o600)
    config.write_text(updated)
    test = subprocess.run(
        ["/usr/local/bin/mihomo", "-t", "-d", "/var/lib/mihomo", "-f", str(config)],
        capture_output=True,
    )
    if test.returncode:
        config.write_text(original)
        raise SystemExit("Mihomo validation failed; original restored")
    match = re.search(r"^secret:\s*(.+)$", original, re.M)
    secret = match.group(1).strip().strip("\"'") if match else ""
    request = urllib.request.Request(
        "http://127.0.0.1:9090/configs?force=true",
        # The controller restricts file paths to /var/lib/mihomo (SAFE_PATHS).
        # Payload reload retains provider files and avoids changing those restrictions.
        data=json.dumps({"payload": updated}).encode(),
        method="PUT",
        headers={"Authorization": "Bearer " + secret, "Content-Type": "application/json"},
    )
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=10) as response:
            print("Mihomo rules reloaded:", response.status)
    except Exception:
        config.write_text(original)
        raise SystemExit("Mihomo reload failed; original file restored") from None
else:
    print("Explicit Longbridge market rules already configured")
