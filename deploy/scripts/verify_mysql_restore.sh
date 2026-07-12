#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $0 /path/to/hys-mysql-YYYYMMDDTHHMMSSZ.sql.gz" >&2
  exit 2
fi

archive=$1
test -r "${archive}"
if [ -f "${archive}.sha256" ]; then
  (cd "$(dirname "${archive}")" && sha256sum -c "$(basename "${archive}").sha256")
fi

container="hys-restore-check-$(date +%s)"
volume="${container}-data"
restore_password=$(openssl rand -hex 24)

cleanup() {
  docker rm -f "${container}" >/dev/null 2>&1 || true
  docker volume rm "${volume}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker volume create "${volume}" >/dev/null
docker run -d --name "${container}" \
  -e MYSQL_ROOT_PASSWORD="${restore_password}" \
  -v "${volume}:/var/lib/mysql" mysql:8.4 >/dev/null

for _ in $(seq 1 60); do
  if docker exec "${container}" mysqladmin ping -uroot -p"${restore_password}" --silent >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
docker exec "${container}" mysqladmin ping -uroot -p"${restore_password}" --silent >/dev/null
gunzip -c "${archive}" | docker exec -i "${container}" mysql -uroot -p"${restore_password}"
docker exec "${container}" mysql -N -uroot -p"${restore_password}" -e 'SHOW DATABASES' | grep -qx 'zhongbei_info'
docker exec "${container}" mysql -N -uroot -p"${restore_password}" zhongbei_info -e 'SHOW TABLES' | grep -qx 'aggregator_contentitem'
