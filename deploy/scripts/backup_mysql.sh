#!/usr/bin/env bash
set -euo pipefail

project_dir=${HYS_PROJECT_DIR:-/home/ubuntu/hys}
backup_dir=${HYS_BACKUP_DIR:-/var/backups/hys}
retention_days=${HYS_BACKUP_RETENTION_DAYS:-7}
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
archive="${backup_dir}/hys-mysql-${timestamp}.sql.gz"
temporary="${archive}.partial"
trap 'rm -f -- "${temporary}"' EXIT

umask 077
mkdir -p "${backup_dir}"
cd "${project_dir}"

docker compose -p hys -f docker-compose.yml exec -T mysql sh -c 'exec mysqldump --no-tablespaces --single-transaction -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"' \
  | gzip -c > "${temporary}"
gzip -t "${temporary}"
mv "${temporary}" "${archive}"
sha256sum "${archive}" > "${archive}.sha256"
find "${backup_dir}" -type f -name 'hys-mysql-*.sql.gz' -mtime +"${retention_days}" -delete
find "${backup_dir}" -type f -name 'hys-mysql-*.sql.gz.sha256' -mtime +"${retention_days}" -delete
