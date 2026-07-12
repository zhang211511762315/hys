# Research Agent deployment runbook

## Preflight

1. Copy `.env.example` to `.env`, replace placeholder secrets, and set the production domain in `DJANGO_ALLOWED_HOSTS`, `PUBLIC_SITE_BASE_URL`, and `CSRF_TRUSTED_ORIGINS`.
2. Run `make check` with the project virtual environment.
3. Run `APP_ENV_FILE=.env docker compose config --quiet`.
4. Back up MySQL and `.env` before migrations.

For the production HTTPS deployment, place the Let's Encrypt material at
`/etc/letsencrypt/live/schoolsearchzzychen.online/` and allow inbound TCP 80
and 443 in the cloud security group. Port 80 intentionally redirects to HTTPS.

## Deploy

```bash
docker compose build web worker agent_worker scheduler
docker compose up -d mysql redis meilisearch
docker compose up -d web worker agent_worker scheduler nginx
docker compose exec web python manage.py migrate --noinput
docker compose exec web python manage.py research_agent_eval --json
```

The Nginx service publishes both ports, serves the ACME webroot, and mounts
`/etc/letsencrypt` read-only. Install the committed systemd unit and timer once:

```bash
sudo cp deploy/systemd/hys-certbot-renew.service /etc/systemd/system/
sudo cp deploy/systemd/hys-certbot-renew.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hys-certbot-renew.timer
```

The timer checks daily and runs `certbot renew --webroot`, then reloads Nginx
without stopping HTTPS traffic. Verify it with `systemctl list-timers
hys-certbot-renew.timer`.

## Backups and restore proof

Run `sudo deploy/scripts/backup_mysql.sh` daily from a root-owned timer; it
writes compressed, checksummed backups to `/var/backups/hys` and keeps seven
days by default. Validate a backup without touching production data with:

```bash
sudo deploy/scripts/verify_mysql_restore.sh /var/backups/hys/hys-mysql-<timestamp>.sql.gz
```

The restore script creates a temporary isolated MySQL container and volume,
checks the checksum and required tables, then removes only its own resources.
Install `deploy/systemd/hys-backup.service` and `deploy/systemd/hys-backup.timer`
with the same `systemctl daemon-reload` and `enable --now` flow as certificate
renewal.

Verify `docker compose ps`, `/healthz`, one research run, its SSE trace and a Replay. Confirm only `agent_worker` consumes the `agent` queue.

The read-only deployment gate is:

```bash
docker compose exec -T web python manage.py research_agent_smoke --json
```

It checks the replay migration, Agent queue route, and positive quota/concurrency settings without printing secrets or calling a model provider.

## Rollback and incidents

Keep the previous image/config and restore them with `docker compose up -d`. Treat schema rollback as a separately reviewed operation; restore the database backup if a migration is not backward compatible. If Redis is unavailable, new async work pauses but MySQL traces remain. If the model is unavailable or the budget is exhausted, deterministic retrieval fallback remains. Repair actions should pass through `AgentApproval`, never public write tools.

Do not claim production P95, availability, paid answer accuracy or 7-day stability until those measurements have actually run. Record model/prompt versions, case count, token/cost totals and failure categories in each report.
