#!/usr/bin/env bash
set -euo pipefail
if [ "$(id -u)" != 0 ]; then echo 'Run with sudo'; exit 1; fi
release="$(cd "$(dirname "$0")/.." && pwd)"
case "$release" in /opt/longbridge-router/releases/*) ;; *) echo 'Unexpected release directory'; exit 1;; esac
if ! id longbridge-router >/dev/null 2>&1; then
    useradd --system --home-dir /var/lib/longbridge-router --shell /sbin/nologin longbridge-router
fi
install -d -m 0700 -o longbridge-router -g longbridge-router /var/lib/longbridge-router
python3 -m venv "$release/.venv"
"$release/.venv/bin/python" -m pip install --no-cache-dir --disable-pip-version-check -q -r "$release/requirements.lock"
# Windows tar sources can carry 0666 modes. Runtime code must be root-owned and immutable to peers.
chmod -R go-w "$release"
cd "$release"
PYTHONPATH="$release" "$release/.venv/bin/python" deploy/bootstrap.py
python3 deploy/configure-routing.py
install -m 0644 deploy/longbridge-router.service /etc/systemd/system/longbridge-router.service
previous="$(readlink /opt/longbridge-router/current || true)"
ln -sfn "$release" /opt/longbridge-router/current
systemctl daemon-reload
systemctl enable longbridge-router.service
systemctl restart longbridge-router.service
healthy=0
for attempt in $(seq 1 20); do
    if curl -fsS --noproxy '*' http://127.0.0.1:18090/healthz >/dev/null; then healthy=1; break; fi
    sleep 1
done
if [ "$healthy" != 1 ]; then
    if [ -n "$previous" ]; then
        ln -sfn "$previous" /opt/longbridge-router/current
        systemctl restart longbridge-router.service
    fi
    echo 'New service failed health check'; exit 1
fi
install -m 0644 deploy/nginx-location.conf /etc/nginx/snippets/longbridge-router-location.conf
cat > /etc/nginx/conf.d/03-longbridge-router-log.conf <<'EOF'
log_format longbridge_safe '$remote_addr [$time_local] "$request_method $uri $server_protocol" $status $body_bytes_sent';
EOF
nginx_config=/etc/nginx/conf.d/sunny-string.conf
if ! grep -q 'include /etc/nginx/snippets/longbridge-router-location.conf;' "$nginx_config"; then
    cp -a "$nginx_config" "$nginx_config.before-longbridge-$(date +%Y%m%d%H%M%S)"
    sed -i '/include \/etc\/nginx\/snippets\/remote-meeting-location.conf;/a\    include /etc/nginx/snippets/longbridge-router-location.conf;' "$nginx_config"
fi
nginx -t
systemctl reload nginx
echo "Longbridge Router deployed from $release"
