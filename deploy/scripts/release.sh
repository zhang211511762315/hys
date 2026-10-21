#!/usr/bin/env bash
# Single-instance maintenance deployment; never touches database services or volumes.
set -euo pipefail
[ "${1:-}" = --maintenance ] || { echo "用法: sudo release.sh --maintenance [镜像标签]" >&2; exit 2; }
cd "$(dirname "$0")/../.."
export HYS_IMAGE="${2:-hys-release:20261020-slim}"
compose=(docker compose -p hys-release -f docker-compose.release.yml)
"${compose[@]}" config --quiet
docker image inspect "$HYS_IMAGE" >/dev/null
saved=$(mktemp)
cp deploy/nginx.conf "$saved"
restore_proxy() {
  cp "$saved" deploy/nginx.conf
  docker exec hys-nginx-1 nginx -t
  docker exec hys-nginx-1 nginx -s reload
  rm -f "$saved"
}
# Existing requests keep their old Nginx worker; new requests get maintenance status.
python3 - <<'PY'
from pathlib import Path
p=Path('deploy/nginx.conf');s=p.read_text()
assert 'proxy_pass http://django_app;' in s
p.write_text(s.replace('proxy_pass http://django_app;', 'return 503;'))
PY
if ! docker exec hys-nginx-1 nginx -t; then cp "$saved" deploy/nginx.conf; rm -f "$saved"; exit 1; fi
docker exec hys-nginx-1 nginx -s reload
trap 'result=$?; if [ "$result" -ne 0 ]; then echo "发布未完成，维护入口保留；原代理配置: $saved。按运维说明恢复后再重跑或回退。" >&2; fi' EXIT
"${compose[@]}" stop --timeout -1 scheduler
"${compose[@]}" stop --timeout -1 web worker agent_worker
"${compose[@]}" up -d --no-deps --pull never web worker agent_worker
for attempt in $(seq 1 60); do
  if docker exec hys-release-web python -c 'import urllib.request; urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8000/healthz",headers={"Host":"schoolsearchzzychen.online","X-Forwarded-Proto":"https"}), timeout=2).close()' >/dev/null 2>&1; then break; fi
  [ "$attempt" -lt 60 ] || exit 1
  sleep 1
done
"${compose[@]}" up -d --no-deps --pull never scheduler
restore_proxy
trap - EXIT
