#!/usr/bin/env bash
#
# Nightly backup of everything that cannot be recreated.
#
# The code is on GitHub and can be redeployed in minutes. The database and the
# uploaded photos cannot: they are the only copy of a year of attendance, and
# attendance is what payroll and any later dispute rest on. A server disk does
# not warn you before it fails.
#
# Install (run once, on the server):
#   chmod +x /root/attendtek/scripts/backup.sh
#   /root/attendtek/scripts/backup.sh          # check it works
#   crontab -e   ->   30 21 * * * /root/attendtek/scripts/backup.sh >> /var/log/attendtek/backup.log 2>&1
#
set -euo pipefail

PROJECT_DIR="/root/attendtek"
BACKUP_DIR="/var/backups/attendtek"
MEDIA_DIR="/var/www/attendtek/media"
KEEP_DAILY=14          # keep two weeks of nightly copies
KEEP_MONTHLY=12        # and the 1st of each month for a year

stamp="$(date +%Y-%m-%d_%H%M)"
day_of_month="$(date +%d)"
mkdir -p "$BACKUP_DIR/daily" "$BACKUP_DIR/monthly"

# The database URL lives in .env; read it without printing it anywhere.
set -a; . "$PROJECT_DIR/.env"; set +a

echo "==> [$(date '+%F %T')] backing up the database"
pg_dump "$DATABASE_URL" --no-owner --no-privileges \
  | gzip > "$BACKUP_DIR/daily/db-$stamp.sql.gz"

echo "==> backing up uploaded files"
if [ -d "$MEDIA_DIR" ] && [ -n "$(ls -A "$MEDIA_DIR" 2>/dev/null)" ]; then
    tar -czf "$BACKUP_DIR/daily/media-$stamp.tar.gz" -C "$(dirname "$MEDIA_DIR")" "$(basename "$MEDIA_DIR")"
else
    echo "    nothing uploaded yet - skipping"
fi

# A backup nobody has ever restored is a guess. Check the dump is readable.
if ! gzip -t "$BACKUP_DIR/daily/db-$stamp.sql.gz"; then
    echo "!! the database dump is corrupt - not rotating anything"
    exit 1
fi
size=$(du -h "$BACKUP_DIR/daily/db-$stamp.sql.gz" | cut -f1)
echo "    database dump is $size and reads back cleanly"

# Keep one copy from the first of each month for longer.
if [ "$day_of_month" = "01" ]; then
    cp "$BACKUP_DIR/daily/db-$stamp.sql.gz" "$BACKUP_DIR/monthly/"
    echo "==> kept a monthly copy"
fi

echo "==> clearing old copies"
find "$BACKUP_DIR/daily" -name "db-*.sql.gz" -mtime "+$KEEP_DAILY" -delete
find "$BACKUP_DIR/daily" -name "media-*.tar.gz" -mtime "+$KEEP_DAILY" -delete
find "$BACKUP_DIR/monthly" -name "db-*.sql.gz" -mtime "+$((KEEP_MONTHLY * 31))" -delete

echo "==> done. Current backups:"
ls -lh "$BACKUP_DIR/daily" | tail -5
echo
echo "To restore into a fresh database:"
echo "  gunzip -c $BACKUP_DIR/daily/db-$stamp.sql.gz | psql \"\$DATABASE_URL\""
