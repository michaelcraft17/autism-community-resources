#!/usr/bin/env bash
# Commit and push a refresh that tools/refresh_source.py finished with status=changed. Used by the
# "Registry refresh" workflow; reads PICKED (source name) and GITHUB_REF_NAME (branch to push to).
#
# Only data/ is committed, plus README.md / index.html when the refresh rewrote the rounded "N+" count copy.
# Anything else modified or staged fails the step. If the push is rejected because the branch moved, the
# refresh is re-applied on top of the new branch head from the already-fetched files (every guard runs again)
# and pushed once more; a second rejection fails the step.
set -euo pipefail
: "${PICKED:?PICKED (source name) is required}"
BRANCH="${GITHUB_REF_NAME:?GITHUB_REF_NAME (branch) is required}"
[[ "${GITHUB_REF:-refs/heads/$BRANCH}" == refs/heads/* ]] || { echo "::error::not a branch ref: $GITHUB_REF"; exit 1; }
OUTCOME=tools/refresh_scratch/outcome.json
MSG=tools/refresh_scratch/commit_message.txt

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

stage_and_commit() {
  local bump
  bump=$(python -c "import json; print(str(bool(json.load(open('$OUTCOME')).get('count_copy'))).lower())")
  git add -A -- data
  if [ "$bump" = true ]; then git add -- README.md index.html; fi
  local staged f
  staged=$(git diff --cached --name-only)
  if [ -z "$staged" ]; then echo "::error::status=changed but nothing under data/ changed"; exit 1; fi
  for f in $staged; do
    case "$f" in
      data/*) ;;
      README.md|index.html) [ "$bump" = true ] || { echo "::error::unexpected staged file $f"; exit 1; } ;;
      *) echo "::error::unexpected staged file $f"; exit 1 ;;
    esac
  done
  if ! git diff --quiet; then
    echo "::error::tracked files changed outside the commit allowlist:"; git diff --name-only; exit 1
  fi
  git commit -q -F "$MSG"
  git show --stat --format='%h %s' HEAD | head -40
}

stage_and_commit
if git push origin "HEAD:refs/heads/$BRANCH"; then
  exit 0
fi

echo "Push rejected: $BRANCH moved. Re-applying the refresh on top of it and trying once more."
cp "$OUTCOME" tools/refresh_scratch/outcome_first.json   # keeps the fetched input (file/date/year) for the message
git fetch --depth=1 origin "$BRANCH"
git reset -q --hard FETCH_HEAD
rm -f community_resources.json   # gitignored, so the reset kept the pre-reset join; rebuilt from the new head
args=(--source "$PICKED" --skip-fetch)
if [ "${ALLOW_DROP:-false}" = true ]; then args+=(--allow-drop); fi
if [ "${ALLOW_CHANGE:-false}" = true ]; then args+=(--allow-change); fi
GITHUB_OUTPUT=/dev/null python tools/refresh_source.py "${args[@]}"
status=$(python -c "import json; print(json.load(open('$OUTCOME'))['status'])")
if [ "$status" = unchanged ]; then
  echo "$BRANCH already has this refresh; nothing to push."
  exit 0
fi
[ "$status" = changed ] || { echo "::error::re-applied refresh ended with status $status"; exit 1; }
stage_and_commit
git push origin "HEAD:refs/heads/$BRANCH"
rm -f tools/refresh_scratch/outcome_first.json
