#!/usr/bin/env bash
# Pull the latest code and restart AttendTek.
#
# Runs two ways:
#   * by hand on the server:  cd /root/attendtek && ./deploy.sh
#   * automatically, when GitHub Actions opens an SSH session after a push
#     (the deploy key in authorized_keys is locked to this script)
set -euo pipefail
cd "$(dirname "$0")"

echo "==> AttendTek deploy started at $(date '+%Y-%m-%d %H:%M:%S %Z')"

echo "==> Pulling latest code"
git fetch --quiet origin main
git reset --hard origin/main
echo "    now at: $(git log -1 --pretty='%h %s')"

echo "==> Installing dependencies"
venv/bin/pip install -q -r requirements.txt

set -a; . ./.env; set +a

echo "==> Applying migrations"
venv/bin/python manage.py migrate --noinput

echo "==> Collecting static files"
venv/bin/python manage.py collectstatic --noinput --clear >/dev/null
echo "    static files updated"

echo "==> Checking for problems before restarting"
venv/bin/python manage.py check --deploy --fail-level ERROR

echo "==> Restarting service"
systemctl restart attendtek
sleep 3

if systemctl is-active --quiet attendtek; then
    echo "==> Deploy finished - service is running"
else
    echo "!! Service failed to start. Last log lines:"
    journalctl -u attendtek -n 30 --no-pager
    exit 1
fi
