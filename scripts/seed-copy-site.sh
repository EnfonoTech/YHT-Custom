#!/usr/bin/env bash
# Seed the test site with a copy of the client's data.
#
# WHY THIS IS A SEPARATE, WINDOWED STEP
# -------------------------------------
# The client database is ~10 GB. Restoring it replays a logical dump into the SAME
# MariaDB instance that serves four LIVE client sites on the other bench
# (almashreq, elco, yas-logistics, designer-stom). That churns the InnoDB buffer
# pool — 4 GB, against 6.7 GB resident and ~3 GB free on an 11 GB box — so the live
# sites lose their hot pages and get slow for as long as the restore runs.
#
# On an idle box it would probably be fine. "Probably fine" is not a thing to do to
# four live ERPs eleven hours outside the maintenance window, so this script exists
# to be run INSIDE it: 02:00-05:00 IST, which is 22:30-01:30 CEST on this host.
#
# WHY THE COPY IS NEEDED AT ALL, measured rather than assumed:
# running the suite against the freshly created EMPTY yht-test gave
#     Ran 244 tests — 16 failures, 25 errors, 103 skipped
# because the suite asserts the client's real figures on purpose (102 negative
# bins, the SAR 3,000 ledger gap, 578 addresses without a district). Those are
# regression guards on actual defects, so they only mean anything against real data.
#
#   Usage:  bash seed-copy-site.sh          # inside the maintenance window
#           FORCE=1 bash seed-copy-site.sh  # skip the window check, deliberately
set -euo pipefail

BENCH=/home/v15/yht-bench
SOURCE=yht-khobhar.enfonoerp.com
TARGET=yht-test

say() { printf '%s\n' "$*"; }

# ── window guard ─────────────────────────────────────────────────────────────
hour=$(date +%H)
if [ "${FORCE:-0}" != "1" ] && [ "$hour" -ge 2 ] && [ "$hour" -lt 22 ]; then
  say "REFUSING: it is $(date +%H:%M) on this host and the maintenance window is 22:30-01:30 CEST."
  say "          MariaDB here also serves four LIVE client sites; a 10 GB restore"
  say "          evicts their buffer-pool pages for the length of the run."
  say "          Re-run inside the window, or FORCE=1 if you have accepted that."
  exit 2
fi

[ -d "$BENCH/sites/$TARGET" ] || { say "REFUSING: $TARGET does not exist. Create it first."; exit 3; }

# ── never overwrite the source ───────────────────────────────────────────────
if [ "$TARGET" = "$SOURCE" ]; then say "REFUSING: target is the source."; exit 4; fi

say "--- backing up $SOURCE (database only, no files) ---"
cd "$BENCH"
sudo -u v15 -H /usr/local/bin/bench --site "$SOURCE" backup | tail -3

LATEST=$(ls -t "$BENCH/sites/$SOURCE/private/backups/"*-database.sql.gz | head -1)
say "--- restoring $LATEST into $TARGET ---"
PW=$(python3 -c "import json;print(json.load(open('$BENCH/sites/common_site_config.json'))['db_root_password'])")
sudo -u v15 -H /usr/local/bin/bench --site "$TARGET" restore "$LATEST" \
  --mariadb-root-password "$PW" --admin-password "yht-test-only" | tail -5

# ── make absolutely sure the copy cannot act like the client site ────────────
say "--- neutering the copy ---"
cd "$BENCH"

# 🔴 mute_emails is the ONE guard that matters. A restored copy carries the client's
# Email Accounts, their Notifications and their scheduled digests; the classic
# copy-site accident is a test site quietly emailing real customers. This kills
# outbound at the framework level, before any of that can fire.
sudo -u v15 -H /usr/local/bin/bench --site "$TARGET" set-config mute_emails 1 >/dev/null
sudo -u v15 -H /usr/local/bin/bench --site "$TARGET" set-config pause_scheduler 1 >/dev/null
sudo -u v15 -H /usr/local/bin/bench --site "$TARGET" set-config allow_tests true >/dev/null
for key in maintenance_mode mail_server mail_port mail_login mail_password; do
  sudo -u v15 -H /usr/local/bin/bench --site "$TARGET" set-config "$key" "" >/dev/null 2>&1 || true
done

# host_name and domains are DELIBERATELY LEFT ALONE. An earlier version cleared them,
# from when this copy was local-only; it is now reachable at yht-test.enfonoerp.com so
# changes can be shown to someone before they touch the client site. Clearing them here
# would silently un-route it after every reseed.
say "    host_name kept: $(python3 -c "import json;print(json.load(open('$BENCH/sites/$TARGET/site_config.json')).get('host_name'))")"

# Belt and braces at the DB level, in case mute_emails is ever removed.
sudo -u v15 -H /usr/local/bin/bench --site "$TARGET" execute frappe.db.sql \
  --kwargs "{'query':'update \`tabEmail Account\` set enable_outgoing=0, enable_incoming=0'}" >/dev/null 2>&1 || true
sudo -u v15 -H /usr/local/bin/bench --site "$TARGET" execute frappe.db.commit >/dev/null 2>&1 || true

sudo -u v15 -H /usr/local/bin/bench --site "$TARGET" migrate | tail -3

say ""
say "--- verifying the copy carries the client's data ---"
sudo -u v15 -H /usr/local/bin/bench --site "$TARGET" execute yht_custom.import_gate.run 2>&1 | tail -14

say ""
say "NEXT, once the suite is green here:"
say "  bench --site $SOURCE set-config allow_tests false"
say "  and leave it false. That is the last reviewer item."
