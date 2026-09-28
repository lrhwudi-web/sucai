#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/opt/material-index/app
DB=/var/lib/material-index/materials.db
ARCHIVE=${1:?Pass the staged release archive path}
EXPECTED_MAIN_SHA=${2:?Pass the current production main.py SHA-256}
EXPECTED_DB_SHA=${3:?Pass the current production db.py SHA-256}
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
STAGE=/tmp/sucai-catalog-stage-$STAMP
BACKUP=/opt/material-index/backups/catalog-$STAMP
DB_SNAPSHOT=/var/lib/material-index/backups/catalog-$STAMP.db
MUTATED=0

rollback() {
  rc=$?
  if [[ $MUTATED == 1 ]]; then
    systemctl stop material-index || true
    cp -a "$BACKUP/main.py" "$ROOT/main.py"
    cp -a "$BACKUP/db.py" "$ROOT/db.py"
    if [[ -d "$BACKUP/dist" ]]; then
      rm -rf -- "$ROOT/fontend/dist"
      mv -- "$BACKUP/dist" "$ROOT/fontend/dist"
    fi
    systemctl start material-index || true
  fi
  echo "RELEASE_FAILED=$STAMP ROLLBACK_ATTEMPTED=$MUTATED" >&2
  exit "$rc"
}
trap rollback ERR

test -f "$ARCHIVE"
test "$(sha256sum "$ROOT/main.py" | cut -d' ' -f1)" == "$EXPECTED_MAIN_SHA"
test "$(sha256sum "$ROOT/db.py" | cut -d' ' -f1)" == "$EXPECTED_DB_SHA"
systemctl is-active --quiet material-index
mkdir -p "$STAGE" "$BACKUP"
tar -xzf "$ARCHIVE" -C "$STAGE"
test -s "$STAGE/main.py"
test -s "$STAGE/db.py"
test -s "$STAGE/dist/index.html"
test ! -e "$STAGE/dist/.env"
/opt/material-index/.venv/bin/python -m py_compile "$STAGE/main.py" "$STAGE/db.py"
NEW_INDEX_SHA=$(sha256sum "$STAGE/dist/index.html" | cut -d' ' -f1)

install -d -o material-index -g material-index -m 750 /var/lib/material-index/backups
sudo -u material-index /opt/material-index/.venv/bin/python - "$DB" "$DB_SNAPSHOT" <<'PY'
import sqlite3
import sys

source = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
target = sqlite3.connect(sys.argv[2])
source.backup(target)
assert target.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
target.close()
source.close()
PY

cp -a "$ROOT/main.py" "$BACKUP/main.py"
cp -a "$ROOT/db.py" "$BACKUP/db.py"
MUTATED=1
systemctl stop material-index
install -o material-index -g material-index -m 644 "$STAGE/main.py" "$ROOT/main.py"
install -o material-index -g material-index -m 644 "$STAGE/db.py" "$ROOT/db.py"
mv -- "$ROOT/fontend/dist" "$BACKUP/dist"
mv -- "$STAGE/dist" "$ROOT/fontend/dist"
chown -R material-index:material-index "$ROOT/fontend/dist"
systemctl start material-index

for _ in $(seq 1 30); do
  if curl --silent --fail --output /dev/null http://127.0.0.1:30285/login; then break; fi
  sleep 1
done
curl --silent --fail --output /dev/null http://127.0.0.1:30285/login
test "$(curl --silent --show-error --fail --max-time 15 https://pr.kairaygolf.com/ | sha256sum | cut -d' ' -f1)" == "$NEW_INDEX_SHA"
systemctl is-active --quiet material-index
sudo -u material-index /opt/material-index/.venv/bin/python - "$DB" "$DB_SNAPSHOT" <<'PY'
import sqlite3
import sys

conn = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
snapshot = sqlite3.connect(f"file:{sys.argv[2]}?mode=ro", uri=True)
assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='customer_catalog_invites'").fetchone()
assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
for table in ("users", "customer_orders", "files"):
    current = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    before = snapshot.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    assert current >= before, f"{table} count fell from {before} to {current}"
    print(f"{table.upper()}={current} (before {before})")
conn.close()
snapshot.close()
PY

trap - ERR
echo "RELEASE_OK=$STAMP BACKUP=$BACKUP DB_SNAPSHOT=$DB_SNAPSHOT"
