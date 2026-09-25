#!/bin/bash
# Unattended re-run of the zero-LLM-cost registry fetchers.
#
# Registries add new orgs over time; re-running a fetcher costs zero tokens
# (plain HTTP + JSON/CSV parsing, no model involved) and merge_new_resources.py
# already dedupes against what's in community_resources.json, so reruns are safe.
#
# Deliberately excluded from this list:
#   - italy_runts_fetch.py   (Playwright-driven against a flaky ASP.NET portal;
#                              needs a human watching, not fire-and-forget)
#   - ukraine_edr_fetch.py   (streams a ~3.2GB bulk export; too heavy for a
#                              routine cron run, rerun by hand occasionally)
#   - bulgaria_companybook_fetch.py (needs COMPANYBOOK_API_KEY; included only
#                              if that env var is set, skipped silently otherwise)
#
# This script NEVER commits or pushes. It only refreshes the working tree and
# leaves the diff for a human (or a Claude session) to review before `git commit`,
# per this repo's standing rule that commits/pushes are never automatic.

set -uo pipefail
export PATH="/opt/homebrew/bin:/opt/anaconda3/bin:/usr/local/bin:$PATH"
cd "$(dirname "$0")/.." || exit 1

LOG_DIR="tools/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/refresh_$(date +%Y%m%d_%H%M%S).log"

BEFORE_COUNT=$(python3 -c "import json; print(len(json.load(open('community_resources.json'))))")

FETCHERS=(
  czech_ares_fetch.py
  estonia_ariregister_fetch.py
  latvia_ur_fetch.py
  slovenia_ajpes_fetch.py
  cyprus_registry_fetch.py
  greece_gemi_fetch.py
  slovakia_rpo_fetch.py
  norway_brreg_fetch.py
  finland_ytj_fetch.py
  france_rna_fetch.py
  belgium_kbo_fetch.py
  netherlands_anbi_fetch.py
)

{
  echo "=== Scheduled refresh started $(date) ==="
  echo "Resource count before: $BEFORE_COUNT"

  for script in "${FETCHERS[@]}"; do
    echo "--- $script ---"
    timeout 300 python3 "tools/$script" || echo "  (non-zero exit or timeout, continuing)"
  done

  if [ -n "${COMPANYBOOK_API_KEY:-}" ]; then
    echo "--- bulgaria_companybook_fetch.py ---"
    timeout 300 python3 tools/bulgaria_companybook_fetch.py || echo "  (non-zero exit, continuing)"
  else
    echo "--- bulgaria_companybook_fetch.py skipped (COMPANYBOOK_API_KEY not set) ---"
  fi

  echo "--- merge_new_resources.py ---"
  python3 tools/merge_new_resources.py

  echo "--- gen_community_data.js ---"
  node gen_community_data.js

  AFTER_COUNT=$(python3 -c "import json; print(len(json.load(open('community_resources.json'))))")
  echo "Resource count after:  $AFTER_COUNT"
  echo "Net new: $((AFTER_COUNT - BEFORE_COUNT))"
  echo "=== Scheduled refresh finished $(date) ==="
  echo ""
  echo "Nothing was committed. Review with 'git status' / 'git diff' and commit by hand."
} >> "$LOG_FILE" 2>&1

echo "Refresh done. Log: $LOG_FILE"
